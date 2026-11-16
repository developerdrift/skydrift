# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Find exposures covering a position, then download cutouts in parallel with a disk cache.

Primary path (IRSA TAP/SIA/SCS were down IRSA-wide on 2026-11-15): list the public IRSA
SPHEREx S3 bucket and read file headers for sky coverage (engine/s3scan.py), then pull pixels
from the IRSA cutout service: https://irsa.ipac.caltech.edu/ibe/data/spherex/<S3 key>?center=&size=
Fallback: the TAP query from SPEC.md, used automatically whenever a cheap startup probe
(tap_available, short timeout) finds TAP responding.

Cache layout: <root>/<ra>_<dec>_<size>/<release>/<planeid>.fits, plus query.ecsv
(the last successful query for that key, used as an offline fallback).
No dates are hardcoded: every run re-queries TAP, so new releases appear on their own.

UNVERIFIED against real data (IRSA TAP was down while this was written):
  - time_bounds_lower is assumed to be MJD.
  - datarelease / metarelease value formats; release_rank() is generic.
"""
import io
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import requests
from astropy.table import Table

IRSA = "https://irsa.ipac.caltech.edu/"
BANDS = [f"D{i}" for i in range(1, 7)]
MAX_WORKERS = 10          # spec: never exceed 10
VISIT_GAP_DAYS = 30.0


class TapError(RuntimeError):
    pass


def tap(query, tries=3, timeout=120):
    """IRSA TAP sync with a hard timeout and exponential backoff."""
    from astropy.io.votable import parse_single_table
    last = None
    for i in range(tries):
        try:
            r = requests.post(f"{IRSA}TAP/sync", timeout=(15, timeout),
                              data=dict(LANG="ADQL", QUERY=query, FORMAT="votable"))
            r.raise_for_status()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return parse_single_table(io.BytesIO(r.content)).to_table()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(5 * 2 ** i)
    raise TapError(f"TAP failed after {tries} tries: {type(last).__name__}: {str(last)[:120]}")


_TAP_OK = None


def tap_available(timeout=6.0):
    """One cheap probe per process: does IRSA TAP answer a trivial query right now?"""
    global _TAP_OK
    if _TAP_OK is None:
        try:
            r = requests.get(f"{IRSA}TAP/sync", timeout=(4, timeout), params=dict(
                LANG="ADQL", FORMAT="csv", QUERY="SELECT TOP 1 planeid FROM spherex.plane"))
            _TAP_OK = r.status_code == 200 and "planeid" in r.text
        except Exception:  # noqa: BLE001
            _TAP_OK = False
    return _TAP_OK


def _s3_table(recs):
    from .s3scan import NAME_RE
    rows = []
    for r in recs:
        m = NAME_RE.search(r["key"])
        rel = r["key"].split("/")[0]
        rows.append(dict(planeid=Path(r["key"]).stem, obsid=f"{m['period']}_{m['seq']}_{m['exp']}",
                         energy_bandpassname=f"SPHEREx-D{r['det']}", time_bounds_lower=float(r["mjd"]),
                         datarelease=rel.upper(), metarelease="", uri="ibe/data/spherex/" + r["key"],
                         s3key=r["key"]))
    return Table(rows=rows) if rows else Table(names=["planeid", "obsid", "energy_bandpassname",
                                                      "time_bounds_lower", "datarelease",
                                                      "metarelease", "uri", "s3key"],
                                               dtype=[str, str, str, float, str, str, str, str])


def find_exposures(ra, dec, size_deg, root, bands=None, log=print):
    """Exposures covering (ra, dec) - never blocks on a scan.

    TAP if the startup probe found it up; otherwise whatever the live coverage index
    (engine/coverage.py, fed by scripts/coverage_daemon.py) knows right now, and the position
    is queued for the daemon so later loads see more. meta['source'] says which path.
    """
    if tap_available():
        try:
            t = query_exposures(ra, dec, size_deg, root, bands, offline_ok=False)
            t.meta["source"] = "IRSA TAP"
            return t
        except TapError as e:
            log(f"  TAP looked up but failed ({e}); using the S3 coverage index")
    from . import coverage
    coverage.request(ra, dec, root)
    t = _s3_table(coverage.lookup(ra, dec, root))
    if bands:
        t = t[[str(b)[-2:] in bands for b in t["energy_bandpassname"]]]
    t = dedupe(t)
    t["band"] = [str(b)[-2:] for b in t["energy_bandpassname"]]
    t["mjd"] = np.asarray(t["time_bounds_lower"], float)
    t["visit"] = cluster_visits(t["mjd"])
    t["release"] = [release_label(r) for r in t]
    t.meta["source"] = "IRSA S3 coverage index (background scan; may grow)"
    return t


def build_query(ra, dec, bands=None):
    bands = bands or BANDS
    blist = ", ".join(f"'SPHEREx-{b}'" for b in bands)
    return f"""SELECT p.obsid, p.planeid, p.datarelease, p.metarelease, p.energy_bandpassname,
  p.time_bounds_lower, p.time_bounds_upper, p.time_exposure,
  p.energy_bounds_lower, p.energy_bounds_upper, a.uri, a.producttype, a.releasetype
FROM spherex.artifact a JOIN spherex.plane p ON a.planeid = p.planeid
WHERE 1 = CONTAINS(POINT('ICRS', {ra:.7f}, {dec:.7f}), p.poly)
  AND p.energy_bandpassname IN ({blist})
ORDER BY p.time_bounds_lower"""


def cutout_url(uri, ra, dec, size_deg):
    uri = str(uri).lstrip("/")
    return f"{IRSA}{uri}?center={ra:.6f},{dec:.6f}d&size={size_deg:g}"


def release_label(row):
    s = str(row["datarelease"]).strip() or str(row["metarelease"]).strip() or "unknown"
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def release_rank(row):
    """Lower is better. DR (data release) beats QR (quick release); higher QR beats lower."""
    s = f"{row['datarelease']} {row['metarelease']}".upper()
    if re.search(r"\bDR\d*", s) or "DR" in s:
        return 0
    m = re.search(r"QR\s*(\d+)", s)
    return 100 - int(m.group(1)) if m else 500


def dedupe(t):
    """Keep one row per (obsid, band), preferring DR1 over quick releases."""
    if len(t) == 0:
        return t
    best = {}
    for k, row in enumerate(t):
        key = (str(row["obsid"]), str(row["energy_bandpassname"]))
        if key not in best or release_rank(row) < release_rank(t[best[key]]):
            best[key] = k
    keep = sorted(best.values(), key=lambda k: float(t["time_bounds_lower"][k]))
    return t[keep]


def cluster_visits(mjds, gap=VISIT_GAP_DAYS):
    """Visit index per element: a new visit starts after a gap > `gap` days."""
    mjds = np.asarray(mjds, float)
    if mjds.size == 0:
        return np.array([], int)
    order = np.argsort(mjds, kind="stable")
    labels = np.empty(mjds.size, int)
    v = 0
    for k, i in enumerate(order):
        if k and mjds[i] - mjds[order[k - 1]] > gap:
            v += 1
        labels[i] = v
    return labels


def key_dir(root, ra, dec, size_deg):
    return Path(root) / f"{ra:.5f}_{dec:+.5f}_{size_deg:g}"


def cutout_dest(root, ra, dec, size_deg, release, planeid):
    return key_dir(root, ra, dec, size_deg) / str(release) / f"{planeid}.fits"


def query_exposures(ra, dec, size_deg, root, bands=None, offline_ok=True):
    """TAP query -> deduped table with band, visit, release columns. Caches the result."""
    kd = key_dir(root, ra, dec, size_deg)
    kd.mkdir(parents=True, exist_ok=True)
    qfile = kd / "query.ecsv"
    try:
        t = tap(build_query(ra, dec, bands))
        t.meta["source"] = "live"
        t.write(qfile, overwrite=True)
    except TapError:
        if not (offline_ok and qfile.exists()):
            raise
        t = Table.read(qfile)
        t.meta["source"] = "cached-query (TAP unreachable)"
        if bands:
            t = t[[str(b)[-2:] in bands for b in t["energy_bandpassname"]]]
    t = dedupe(t)
    t["band"] = [str(b)[-2:] for b in t["energy_bandpassname"]]
    t["mjd"] = np.asarray(t["time_bounds_lower"], float)
    t["visit"] = cluster_visits(t["mjd"])
    t["release"] = [release_label(r) for r in t]
    return t


def _download(url, dest, tries=4, timeout=120):
    for i in range(tries):
        try:
            r = requests.get(url, timeout=(15, timeout))
            r.raise_for_status()
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.replace(dest)
            return dest
        except Exception:  # noqa: BLE001
            if i < tries - 1:
                time.sleep(2 * 2 ** i)
    return None


def fetch_cutouts(t, ra, dec, size_deg, root, workers=MAX_WORKERS, downloader=None,
                  progress=None):
    """Download (or reuse cached) cutouts for each row. Returns a list of Path|None.

    `downloader(url, dest)` can be swapped out in tests.
    """
    workers = min(workers, MAX_WORKERS)
    downloader = downloader or _download
    kd = key_dir(root, ra, dec, size_deg)
    paths = [None] * len(t)
    todo = {}
    for i, row in enumerate(t):
        dest = cutout_dest(root, ra, dec, size_deg, row["release"], row["planeid"])
        if dest.exists() and dest.stat().st_size > 0:
            paths[i] = dest
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            todo[i] = (cutout_url(row["uri"], ra, dec, size_deg), dest)
    done = len(t) - len(todo)
    if progress:
        progress(done, len(t))
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(downloader, url, dest): i for i, (url, dest) in todo.items()}
            for f in as_completed(futs):
                try:
                    paths[futs[f]] = f.result()
                except Exception:  # noqa: BLE001
                    paths[futs[f]] = None
                done += 1
                if progress:
                    progress(done, len(t))
    return paths
