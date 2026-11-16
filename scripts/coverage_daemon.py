# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Background coverage scanner + preset cutout prefetcher. Fully decoupled from the app.

Usage: python scripts/coverage_daemon.py [--minutes 60] [--no-prefetch]

- Searches the IRSA SPHEREx S3 bucket for exposures covering the five presets and any
  positions the app queued (cache/coverage/queue/). Round-robin over targets, one candidate
  planning period at a time, so every target gets early results.
- Every header read is appended to cache/s3index/headers.jsonl immediately; covering
  exposures are appended to cache/coverage/<name>.jsonl and status to <name>.status.json
  after each period. The app reads these live.
- Prefetches cutouts for preset targets as soon as they are found (max 10 workers to IRSA).
"""
import argparse
import json
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
import astropy  # noqa: E402,F401  (import before touching its logger)
import logging  # noqa: E402
logging.getLogger("astropy").setLevel(logging.ERROR)
from engine import fetch, views  # noqa: E402
from engine.coverage import queue_dir  # noqa: E402
from engine.s3scan import (HeaderIndex, Listing, _seq_exp, _vec, contains,  # noqa: E402
                           sep_deg)
from engine.targets import preset_positions  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--minutes", type=float, default=60)
ap.add_argument("--no-prefetch", action="store_true")
ap.add_argument("--per-period", type=int, default=24)
ap.add_argument("--until", default=None, help="local wall-clock end time HH:MM (overrides --minutes)")
ap.add_argument("--truth", action="store_true", help="also scan the truth-check stars")
a = ap.parse_args()
if a.until:
    import datetime as _dt
    _now = _dt.datetime.now()
    _end = _now.replace(hour=int(a.until[:2]), minute=int(a.until[3:5]), second=0, microsecond=0)
    a.minutes = max(1.0, (_end - _now).total_seconds() / 60)
CACHE = ROOT / "cache"
COV = CACHE / "coverage"
COV.mkdir(parents=True, exist_ok=True)
T0 = time.time()
LOG = COV / "daemon.log"


def log(*m):
    line = f"{time.strftime('%H:%M:%S')} [{(time.time() - T0) / 60:5.1f}m] " + " ".join(map(str, m))
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def time_left():
    return a.minutes * 60 - (time.time() - T0)


idx, lst = HeaderIndex(CACHE), Listing(CACHE)
dl_pool = ThreadPoolExecutor(max_workers=10)
pending_dl = []


class Target:
    def __init__(self, name, ra, dec, prefetch_size=None):
        self.name, self.ra, self.dec, self.size = name, ra, dec, prefetch_size
        self.cov_path = COV / f"{name}.jsonl"
        self.st_path = COV / f"{name}.status.json"
        self.keys = set()
        if self.cov_path.exists():
            self.keys = {json.loads(l)["key"] for l in self.cov_path.read_text().splitlines() if l}
        self.cands, self.done = [], 0

    def status(self, state):
        self.st_path.write_text(json.dumps(dict(
            name=self.name, ra=self.ra, dec=self.dec, state=state, found=len(self.keys),
            periods_done=self.done, periods_total=len(self.cands),
            updated=time.strftime("%Y-%m-%d %H:%M:%S"))))

    def add(self, recs):
        new = [r for r in recs if r["key"] not in self.keys]
        if new:
            with self.cov_path.open("a") as f:
                for r in new:
                    f.write(json.dumps(r) + "\n")
                    self.keys.add(r["key"])
            if self.size and not a.no_prefetch:
                t = fetch._s3_table(new)
                t["release"] = [fetch.release_label(r) for r in t]
                for row in t:
                    url = fetch.cutout_url(row["uri"], self.ra, self.dec, self.size)
                    dest = fetch.cutout_dest(CACHE, self.ra, self.dec, self.size, row["release"], row["planeid"])
                    if not dest.exists():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        pending_dl.append(dl_pool.submit(fetch._download, url, dest))
        return len(new)


# ---- shared stage A: listing + ~24 D1 headers per period -> per-period scan planes ----
periods = lst.periods()
firsts, sample = {}, []
for name, pref in periods.items():
    f = {}
    for k in lst.det_keys(pref, 1):
        s_, e_ = _seq_exp(k)
        if e_ == 1:
            f[s_] = k
    firsts[pref] = sorted(f.items())
    step = max(1, len(firsts[pref]) // a.per_period)
    sample += [k for _, k in firsts[pref][::step]]
lst.save()
log(f"stage A: {len(periods)} periods, {sum(len(v) for v in firsts.values())} sequences, "
    f"reading {len(sample)} sample headers")
recs = idx.get_many(sample)
planes = {}
by_p = {}
for r in recs:
    by_p.setdefault("/".join(r["key"].split("/")[:3]) + "/", []).append(_vec(r["ra"], r["dec"]))
for pref, V in by_p.items():
    V = np.array(V)
    if len(V) >= 4:
        n = np.linalg.svd(V)[2][-1]
        planes[pref] = (n, float(np.percentile(np.degrees(np.arcsin(np.clip(np.abs(V @ n), 0, 1))), 95)))
    else:
        planes[pref] = (None, 90.0)
log(f"stage A done: {len(planes)} period planes")


def candidates(ra, dec):
    tv = _vec(ra, dec)
    out = []
    for pref, (n, r95) in planes.items():
        dist = 0.0 if n is None else float(np.degrees(np.arcsin(min(1.0, abs(float(n @ tv))))))
        if dist < r95 + 10.0:
            out.append((dist - r95, pref))
    return [p for _, p in sorted(out)]


def scan_period(t, pref):
    fs = firsts[pref]
    rs = idx.get_many([k for _, k in fs[::2]])
    close = {_seq_exp(r["key"])[0] for r in rs if sep_deg(r["ra"], r["dec"], t.ra, t.dec) < 42}
    fill = [k for s_, k in fs if any(abs(s_ - c) <= 1 for c in close)]
    hit = {_seq_exp(r["key"])[0] for r in idx.get_many(fill)
           if sep_deg(r["ra"], r["dec"], t.ra, t.dec) < 11.5}
    found = []
    if hit:
        for det in range(1, 7):
            keys = [k for k in lst.det_keys(pref, det) if _seq_exp(k)[0] in hit]
            found += [r for r in idx.get_many(keys) if contains(r["fp"], t.ra, t.dec)]
        lst.save()
    return found


targets = []
for p in preset_positions():
    t = Target(p["key"], p["ra"], p["dec"], views.cutout_size(p["fov"]))
    t.cands = candidates(t.ra, t.dec)
    t.status("scanning")
    targets.append(t)
    log(f"{t.name}: {len(t.cands)} candidate periods (already have {len(t.keys)})")


if a.truth:
    from astropy.time import Time
    from engine.targets import position_at
    from engine.truthstars import stars as truth_stars
    _mid = Time(2025.9, format="jyear").mjd
    for st in truth_stars():
        ra_, dec_ = position_at(st, _mid)
        ra_, dec_ = round(ra_, 5), round(dec_, 5)
        if any(abs(o.ra - ra_) < 1e-4 and abs(o.dec - dec_) < 1e-4 for o in targets):
            continue
        tag = "truth_" + "".join(ch if ch.isalnum() else "_" for ch in st["name"])
        t = Target(tag, ra_, dec_, views.cutout_size(8.0))
        t.cands = candidates(t.ra, t.dec)
        t.status("scanning")
        targets.append(t)
    log(f"truth-check stars added: {sum(1 for t in targets if t.name.startswith('truth_'))}")


def check_queue():
    for q in sorted(queue_dir(CACHE).glob("*.json")):
        try:
            d = json.loads(q.read_text())
        except ValueError:
            continue
        if any(abs(o.ra - d["ra"]) < 1e-4 and abs(o.dec - d["dec"]) < 1e-4 for o in targets):
            q.unlink()
            continue
        t = Target(q.stem, d["ra"], d["dec"])
        t.cands = candidates(t.ra, t.dec)
        t.status("scanning")
        targets.append(t)
        q.unlink()
        log(f"queued {t.name}: {len(t.cands)} candidate periods")


rnd = 0
while time_left() > 0:
    check_queue()
    active = [t for t in targets if t.done < len(t.cands)]
    if not active:
        # Everything searched: wait for app-queued positions until the deadline.
        for t in targets:
            t.status("complete")
        time.sleep(min(60, max(1, time_left())))
        continue
    for t in active:
        if time_left() <= 0:
            break
        pref = t.cands[t.done]
        n_new = t.add(scan_period(t, pref))
        t.done += 1
        t.status("scanning")
        if n_new:
            log(f"{t.name}: +{n_new} in {pref.split('/')[2]} -> {len(t.keys)} total "
                f"({t.done}/{len(t.cands)} periods)")
    rnd += 1
    if rnd % 3 == 0:
        done_dl = sum(f.done() for f in pending_dl)
        log(f"round {rnd}: cutout prefetch {done_dl}/{len(pending_dl)} done; "
            + ", ".join(f"{t.name}={len(t.keys)}" for t in targets))

for t in targets:
    t.status("complete" if t.done >= len(t.cands) else "partial (time cap)")
log("scan finished; finishing cutout downloads (cancelled if the time cap is hit) ...")
dl_pool.shutdown(wait=True, cancel_futures=time_left() <= 0)
ok = sum(1 for f in pending_dl if not f.cancelled() and f.result() is not None)
log(f"daemon done: {ok}/{len(pending_dl)} cutouts fetched; "
    + ", ".join(f"{t.name}={len(t.keys)} ({t.done}/{len(t.cands)})" for t in targets))
