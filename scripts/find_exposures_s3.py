# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Find SPHEREx DR1 exposures (all detectors) whose footprint contains RA/Dec, via S3 headers.

Usage: python scripts/find_exposures_s3.py RA DEC NAME [--release dr1] [--cap-min 30]
Writes cache/s3index/<NAME>_covering.json. Used while IRSA TAP/SIA are down.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.s3scan import HeaderIndex, NAME_RE, contains, s3_list, sep_deg  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("ra", type=float)
ap.add_argument("dec", type=float)
ap.add_argument("name")
ap.add_argument("--release", default="dr1")
ap.add_argument("--cap-min", type=float, default=30)
ap.add_argument("--stride", type=int, default=5)
ap.add_argument("--periods", default=None, help="regex filter on period names")
ap.add_argument("--adet", type=int, default=1, help="detector used for stage A/B sampling")
a = ap.parse_args()
T0 = time.time()
idx = HeaderIndex(ROOT / "cache")


def log(*m):
    print(f"[{(time.time() - T0) / 60:5.1f} min]", *m, flush=True)


def over_cap():
    return time.time() - T0 > a.cap_min * 60


# --- listing (cached) ---
lst_file = ROOT / "cache" / "s3index" / f"{a.release}_det_listing.json"
listing = json.loads(lst_file.read_text()) if lst_file.exists() else {}
periods, _ = s3_list(f"{a.release}/level2/")
if a.periods:
    periods = [p for p in periods if re.search(a.periods, p)]
log(len(periods), "periods")


def det_keys(period_prefix, det):
    ck = f"{period_prefix}|{det}"
    if ck not in listing:
        vers, _ = s3_list(period_prefix)
        vers = sorted(vers, key=lambda v: int(re.search(r"-v(\d+)-", v).group(1)) if re.search(r"-v(\d+)-", v) else 0)
        if not vers:
            listing[ck] = []
        else:
            _, keys = s3_list(f"{vers[-1]}{det}/")
            listing[ck] = [k for k, s in keys if k.endswith(".fits")]
    return listing[ck]


def parse(k):
    m = NAME_RE.search(k)
    return int(m["seq"]), int(m["exp"])


# --- stage A: coarse sample, det 1, exposure 1, every 40th sequence ---
per_period = {}
sample = []
for p in periods:
    keys = det_keys(p, a.adet)
    first = sorted({parse(k)[0]: k for k in keys if parse(k)[1] == 1}.items())
    per_period[p] = first
    sample += [k for _, k in first[::a.stride]]
lst_file.write_text(json.dumps(listing))
log("stage A: reading", len(sample), "headers")
recs = idx.get_many(sample)
best = {}
for r in recs:
    p = r["key"].split("/l2b-")[0].rsplit("/", 1)[0] + "/"
    p = "/".join(r["key"].split("/")[:3]) + "/"
    d = sep_deg(r["ra"], r["dec"], a.ra, a.dec)
    if p not in best or d < best[p][0]:
        best[p] = (d, parse(r["key"])[0])
cands = sorted([(d, p, s) for p, (d, s) in best.items() if d < 20])
log("stage A done; candidate periods (<20 deg):", [(p.split('/')[2], round(d, 1)) for d, p, s in cands])

# --- stage B: candidate periods, det 1 every 4th seq within +-80 of the best sample ---
close_seqs = []
for d, p, s0 in cands:
    if over_cap():
        break
    seqs = [(s, k) for s, k in per_period[p] if abs(s - s0) <= 3 * a.stride + 10]
    rs = idx.get_many([k for _, k in seqs])
    near = [parse(r["key"])[0] for r in rs if sep_deg(r["ra"], r["dec"], a.ra, a.dec) < 11]
    if near:
        close_seqs.append((p, min(near) - 4, max(near) + 4))
log("stage B done; seq windows:", [(p.split('/')[2], lo, hi) for p, lo, hi in close_seqs])

# --- stage C: all detectors, all exposures in those windows; exact footprint test ---
covering = []
for p, lo, hi in close_seqs:
    for det in range(1, 7):
        if over_cap():
            break
        keys = [k for k in det_keys(p, det) if lo <= parse(k)[0] <= hi]
        rs = idx.get_many(keys)
        covering += [r for r in rs if contains(r["fp"], a.ra, a.dec)]
    lst_file.write_text(json.dumps(listing))
    log(p.split('/')[2], "covering so far:", len(covering))

out = ROOT / "cache" / "s3index" / f"{a.name}_covering.json"
if out.exists():  # merge with earlier runs
    covering += [r for r in json.loads(out.read_text())["covering"] if r["key"] not in {c["key"] for c in covering}]
out.write_text(json.dumps(dict(ra=a.ra, dec=a.dec, release=a.release, capped=over_cap(),
                               minutes=round((time.time() - T0) / 60, 1),
                               covering=sorted(covering, key=lambda r: r["mjd"])), indent=0))
by_det = {}
for r in covering:
    by_det[r["det"]] = by_det.get(r["det"], 0) + 1
log("DONE covering exposures:", len(covering), "by detector:", dict(sorted(by_det.items())),
    "capped:", over_cap(), "->", out.name)
