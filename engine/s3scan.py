# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Fallback exposure finder for when IRSA's query services (TAP/SIA) are down.

Lists the public IRSA SPHEREx S3 bucket and reads only the IMAGE header of each file
via an HTTP range request (~58 KB), to find exposures whose footprint contains a target.
The pixels then come from the IRSA cutout service: ibe/data/spherex/<S3 key>?center=&size=

Every header that is read is cached in cache/s3index/headers.jsonl, so later targets reuse it.
"""
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from astropy.wcs import WCS

BUCKET = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
HEADER_BYTES = 57600
NAME_RE = re.compile(r"level2_(?P<period>[^_]+_[^_]+)_(?P<seq>\d+)_(?P<exp>\d+)D(?P<det>\d)_spx_")
_lock = threading.Lock()


def s3_list(prefix, delimiter="/"):
    """All common prefixes and (key, size) under prefix, following pagination."""
    pres, keys, tok = [], [], None
    while True:
        p = {"list-type": "2", "delimiter": delimiter, "prefix": prefix, "max-keys": 1000}
        if tok:
            p["continuation-token"] = tok
        for i in range(4):
            try:
                r = requests.get(BUCKET, params=p, timeout=(10, 60))
                r.raise_for_status()
                break
            except Exception:  # noqa: BLE001
                if i == 3:
                    raise
                time.sleep(2 * 2 ** i)
        x = ET.fromstring(r.content)
        pres += [e.find("s:Prefix", NS).text for e in x.findall("s:CommonPrefixes", NS)]
        keys += [(e.find("s:Key", NS).text, int(e.find("s:Size", NS).text))
                 for e in x.findall("s:Contents", NS)]
        t = x.find("s:NextContinuationToken", NS)
        tok = t.text if t is not None else None
        if not tok:
            return pres, keys


def parse_image_header(raw):
    """Walk FITS headers in the first bytes; return the first header with NAXIS=2 data."""
    off = 0
    while off + 2880 <= len(raw):
        end = None
        for b in range(off, len(raw) - 2879, 2880):
            block = raw[b:b + 2880]
            for c in range(0, 2880, 80):
                if block[c:c + 8] == b"END     ":
                    end = b + 2880
                    break
            if end:
                break
        if end is None:
            return None
        h = fits.Header.fromstring(raw[off:end].decode("ascii", "replace"))
        if h.get("NAXIS", 0) == 2:
            return h
        n = h.get("NAXIS", 0)
        dlen = abs(h.get("BITPIX", 8)) // 8 * int(np.prod([h[f"NAXIS{i}"] for i in range(1, n + 1)])) if n else 0
        off = end + ((dlen + 2879) // 2880) * 2880
    return None


def header_record(key):
    for i in range(4):
        try:
            r = requests.get(BUCKET + key, headers={"Range": f"bytes=0-{HEADER_BYTES - 1}"},
                             timeout=(10, 60))
            r.raise_for_status()
            break
        except Exception:  # noqa: BLE001
            if i == 3:
                return None
            time.sleep(2 * 2 ** i)
    h = parse_image_header(r.content)
    if h is None:
        return None
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        w = WCS(h)
        fp = w.calc_footprint(axes=(h["NAXIS1"], h["NAXIS2"]))
        c = w.pixel_to_world_values(h["NAXIS1"] / 2, h["NAXIS2"] / 2)
    m = NAME_RE.search(key)
    return dict(key=key, ra=float(c[0]), dec=float(c[1]), fp=fp.round(5).tolist(),
                mjd=h.get("MJD-AVG", h.get("MJD-OBS")), det=int(m["det"]) if m else None)


class HeaderIndex:
    def __init__(self, root):
        self.path = Path(root) / "s3index" / "headers.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.recs = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                d = json.loads(line)
                self.recs[d["key"]] = d

    def get_many(self, keys, workers=10):
        todo = [k for k in keys if k not in self.recs]
        if todo:
            with ThreadPoolExecutor(min(workers, 10)) as ex:
                for rec in ex.map(header_record, todo):
                    if rec:
                        with _lock:
                            self.recs[rec["key"]] = rec
                            with self.path.open("a") as f:
                                f.write(json.dumps(rec) + "\n")
        return [self.recs[k] for k in keys if k in self.recs]


def sep_deg(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(np.radians, (ra1, dec1, ra2, dec2))
    c = np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(r1 - r2)
    return np.degrees(np.arccos(np.clip(c, -1, 1)))


def contains(fp, ra, dec):
    """Point-in-footprint test in a local tangent plane around the target."""
    fp = np.asarray(fp)
    dra = ((fp[:, 0] - ra + 180) % 360 - 180) * np.cos(np.radians(dec))
    ddec = fp[:, 1] - dec
    inside = False
    n = len(fp)
    for i in range(n):
        x1, y1, x2, y2 = dra[i], ddec[i], dra[(i + 1) % n], ddec[(i + 1) % n]
        if (y1 > 0) != (y2 > 0) and 0 < x1 + (0 - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


# ---------------------------------------------------------------------------
# Coverage search (moved here from scripts/find_exposures_s3.py)
# ---------------------------------------------------------------------------
REL_RE = re.compile(r"^(dr|qr)(\d+)/$")
VER_RE = re.compile(r"-v(\d+)-")


def release_order(rel):
    """Sort key: data releases before quick releases, newer first."""
    m = REL_RE.match(rel)
    return (0 if m[1] == "dr" else 1, -int(m[2])) if m else (9, 0)


class Listing:
    """Cached S3 listings: releases -> periods -> latest version dir -> detector keys."""

    def __init__(self, root):
        self.path = Path(root) / "s3index" / "listing.json"
        self.d = json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self):
        self.path.write_text(json.dumps(self.d))

    def periods(self, refresh=True):
        """{period_name: period_prefix} taking each period from the best release that has it.
        Always re-lists (cheap) so new releases and new periods are picked up automatically."""
        if refresh or "periods" not in self.d:
            rels, _ = s3_list("")
            rels = sorted([r for r in rels if REL_RE.match(r)], key=release_order)
            out = {}
            for rel in rels:
                pres, _ = s3_list(f"{rel}level2/")
                for p in pres:
                    out.setdefault(p.rstrip("/").split("/")[-1], p)
            self.d["periods"] = out
        return self.d["periods"]

    def det_keys(self, period_prefix, det):
        """All exposures of one detector in a period. A period can hold several processing
        directories (e.g. l2b-v27-... plus a small l2b_retry-v27-...); they are merged, with
        newer versions and then retry directories overriding the same (seq, exp)."""
        ck = f"{period_prefix}|{det}"
        if ck not in self.d:
            vers, _ = s3_list(period_prefix)

            def vkey(v):
                m = VER_RE.search(v)
                return (int(m[1]) if m else 0, "retry" in v)
            best = {}
            for v in sorted(vers, key=vkey):
                _, ks = s3_list(f"{v}{det}/")
                for k, _ in ks:
                    m = NAME_RE.search(k)
                    if k.endswith(".fits") and m:
                        best[(int(m["seq"]), int(m["exp"]))] = k
            self.d[ck] = [best[q] for q in sorted(best)]
        return self.d[ck]


def _seq_exp(key):
    m = NAME_RE.search(key)
    return int(m["seq"]), int(m["exp"])


def _vec(ra, dec):
    r, d = np.radians(ra), np.radians(dec)
    return np.array([np.cos(d) * np.cos(r), np.cos(d) * np.sin(r), np.sin(d)])


def find_covering(ra, dec, root, per_period=24, cap_min=40.0, log=print):
    """Exposures (all detectors) whose footprint contains (ra, dec).

    Survey geometry measured from DR1 headers: consecutive sequences jump ~28 deg along a
    great circle (one orbit is ~13 sequences); exposures inside a sequence step ~0.2 deg;
    D1-D3 centres are 3.86 deg apart in a row and D4-D6 see the same sky as D1-D3.
    Stage A: ~24 D1 headers per period -> fit that period's scan plane.
    Stage B: periods whose plane passes near the target -> every 2nd sequence, then fill in
             the neighbours of any sequence within 45 deg.
    Stage C: sequences whose D1 centre is within 11.5 deg -> all detectors and exposures,
             exact footprint test.
    """
    t0 = time.time()
    out_path = Path(root) / "s3index" / f"cover2_{ra:.4f}_{dec:+.4f}.json"
    if out_path.exists():
        return json.loads(out_path.read_text())["covering"]
    idx, lst = HeaderIndex(root), Listing(root)
    periods = lst.periods()
    firsts = {}
    sample = []
    for name, pref in periods.items():
        f = {}
        for k in lst.det_keys(pref, 1):
            s_, e_ = _seq_exp(k)
            if e_ == 1:
                f[s_] = k
        firsts[pref] = sorted(f.items())
        step = max(1, len(firsts[pref]) // per_period)
        sample += [k for _, k in firsts[pref][::step]]
    lst.save()
    log(f"  s3scan stage A: {len(periods)} periods, {len(sample)} sampled headers")
    recs = idx.get_many(sample)
    tv = _vec(ra, dec)
    by_p = {}
    for r in recs:
        by_p.setdefault("/".join(r["key"].split("/")[:3]) + "/", []).append(_vec(r["ra"], r["dec"]))
    cands = []
    for pref, V in by_p.items():
        V = np.array(V)
        if len(V) < 4:
            cands.append((0.0, pref))
            continue
        n = np.linalg.svd(V)[2][-1]
        resid = np.degrees(np.arcsin(np.clip(np.abs(V @ n), 0, 1)))
        dist = np.degrees(np.arcsin(min(1.0, abs(float(n @ tv)))))
        if dist < np.percentile(resid, 95) + 10.0:
            cands.append((dist, pref))
    cands.sort()
    log(f"  s3scan stage B: {len(cands)} candidate periods")
    near = {}
    for _, pref in cands:
        if time.time() - t0 > cap_min * 60:
            log("  s3scan: time cap reached in stage B")
            break
        fs = firsts[pref]
        rs = idx.get_many([k for _, k in fs[::2]])
        close = {_seq_exp(r["key"])[0] for r in rs if sep_deg(r["ra"], r["dec"], ra, dec) < 42}
        fill = [k for s_, k in fs if any(abs(s_ - c) <= 1 for c in close)]
        hit = sorted({_seq_exp(r["key"])[0] for r in idx.get_many(fill)
                      if sep_deg(r["ra"], r["dec"], ra, dec) < 11.5})
        if hit:
            near[pref] = hit
    covering = []
    for pref, seqs_ in near.items():
        for det in range(1, 7):
            keys = [k for k in lst.det_keys(pref, det) if _seq_exp(k)[0] in set(seqs_)]
            covering += [r for r in idx.get_many(keys) if contains(r["fp"], ra, dec)]
    lst.save()
    capped = time.time() - t0 > cap_min * 60
    log(f"  s3scan: {len(covering)} covering exposures from {len(near)} periods in "
        f"{(time.time() - t0) / 60:.1f} min" + (" (CAPPED - incomplete)" if capped else ""))
    if not capped:
        out_path.write_text(json.dumps(dict(ra=ra, dec=dec, covering=covering)))
    return covering
