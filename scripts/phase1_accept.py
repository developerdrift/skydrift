# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Phase 1 acceptance: visit-blink GIF of a high-proper-motion star, with numbers.

Usage: python scripts/phase1_accept.py [target_key] [--fov 4]
Writes phase1_out/<key>_visit_blink_<band>.gif and <key>_phase1.json
"""
import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
from astropy.stats import sigma_clipped_stats
from astropy.time import Time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
import astropy  # noqa: E402,F401  (import before touching its logger)
import logging  # noqa: E402
logging.getLogger("astropy").setLevel(logging.ERROR)
from engine import fetch, measure, pipeline, regrid, render, stack  # noqa: E402
from engine.targets import TARGETS, position_at  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("key", nargs="?", default="barnard")
ap.add_argument("--fov", type=float, default=4.0)
ap.add_argument("--display-saturated", action="store_true",
                help="DISPLAY ONLY: also keep OVERFLOW/BLOOM/SUR_ERROR/TRANSIENT pixels (saturated cores)")
a = ap.parse_args()
OUT = ROOT / "phase1_out"
OUT.mkdir(exist_ok=True)
CACHE = ROOT / "cache"
tg = TARGETS[a.key]
mjd_mid = Time(2025.9, format="jyear").mjd
ra0, dec0 = position_at(a.key, mjd_mid)
size = round(a.fov / 60 * 1.15, 4)
print(f"{tg['name']}: grid centre {ra0:.5f} {dec0:+.5f}, fov {a.fov}', cutout {size} deg")
print("TAP available:", fetch.tap_available())

t = fetch.find_exposures(ra0, dec0, size, CACHE)
print(f"exposures: {len(t)} via {t.meta.get('source')}")
paths = fetch.fetch_cutouts(t, ra0, dec0, size, CACHE,
                            progress=lambda d, n: print(f"  cutouts {d}/{n}", end="\r"))
print(f"\n  ok {sum(p is not None for p in paths)}, failed {sum(p is None for p in paths)}")
recs = [dict(path=p, band=str(r["band"]), visit=int(r["visit"]), mjd=float(r["mjd"]),
             planeid=str(r["planeid"]), obsid=str(r["obsid"]), release=str(r["release"]))
        for r, p in zip(t, paths)]
from engine.calibrate import DEFAULT_MASK, FLAG_BITS  # noqa: E402
mask = DEFAULT_MASK
sfx = ""
if a.display_saturated:
    for b, n in FLAG_BITS.items():
        if n in ("OVERFLOW", "BLOOM", "SUR_ERROR", "TRANSIENT"):
            mask &= ~(1 << b)
    sfx = "_display_saturated"
frames, w = pipeline.build_frames(recs, ra0, dec0, a.fov, mask_bits=mask)
print(f"frames: {len(frames)}; flag fraction (masked) mean "
      f"{np.mean([f['flag_frac_masked'] for f in frames]):.3f}")

summary = dict(target=tg["name"], key=a.key, mask_bits=int(mask),
               display_saturated=a.display_saturated, data_source=t.meta.get("source"),
               n_exposures=len(t), n_frames=len(frames), bands={})
scale = regrid.NATIVE_ARCSEC / 2
for band in sorted({f["band"] for f in frames}):
    fs = [f for f in frames if f["band"] == band]
    stacks = stack.group_stacks(fs)
    info = dict(n_frames=len(fs), visits=[dict(date=Time(s["mjd_mean"], format="mjd").iso[:10],
                                               n=s["n"], wav=[round(x, 3) for x in s["wav_range"]])
                                          for s in stacks])
    summary["bands"][band] = info
    if len(stacks) < 2:
        continue
    gif = OUT / f"{a.key}_visit_blink_{band}{sfx}.gif"
    pipeline.visit_blink(fs, band, gif)
    info["gif"] = gif.name
    # target: centroid near prediction in every visit stack
    pos = []
    for s in stacks:
        px, py = w.wcs_world2pix([position_at(a.key, s["mjd_mean"])], 0)[0]
        cx, cy = measure.centroid(s["img"], px, py, r=4)
        pos.append((s["mjd_mean"], px, py, cx, cy))
    p0, p1 = pos[0], pos[-1]
    dt_yr = (p1[0] - p0[0]) / 365.25
    info["target"] = dict(
        dt_days=round(p1[0] - p0[0], 1),
        predicted_shift_arcsec=round(float(np.hypot(p1[1] - p0[1], p1[2] - p0[2]) * scale), 2),
        measured_shift_arcsec=round(float(np.hypot(p1[3] - p0[3], p1[4] - p0[4]) * scale), 2),
        offsets_from_prediction_arcsec=[round(float(np.hypot(c[3] - c[1], c[4] - c[2]) * scale), 2)
                                        for c in pos])
    # neighbours: peaks in the all-epoch stack, > 8 sigma, away from the target and edges
    allst = stack.all_epoch(fs)["img"]
    _, med, sd = sigma_clipped_stats(allst[np.isfinite(allst)])
    from scipy.ndimage import maximum_filter
    pk = (allst == maximum_filter(np.nan_to_num(allst, nan=-1e30), size=7)) & (allst > med + 8 * sd)
    ys, xs = np.nonzero(pk)
    tx, ty = w.wcs_world2pix([position_at(a.key, mjd_mid)], 0)[0]
    n = allst.shape[0]
    shifts = []
    for x, y in zip(xs, ys):
        if np.hypot(x - tx, y - ty) < 12 or min(x, y, n - 1 - x, n - 1 - y) < 8:
            continue
        c0 = measure.centroid(stacks[0]["img"], x, y, r=3)
        c1 = measure.centroid(stacks[-1]["img"], x, y, r=3)
        if np.isfinite(c0[0]) and np.isfinite(c1[0]):
            shifts.append(np.hypot(c1[0] - c0[0], c1[1] - c0[1]) * scale)
    info["neighbours"] = dict(n=len(shifts),
                              median_shift_arcsec=round(float(np.median(shifts)), 2) if shifts else None,
                              p90_shift_arcsec=round(float(np.percentile(shifts, 90)), 2) if shifts else None)
    print(f"{band}: {len(stacks)} visits; target shift measured "
          f"{info['target']['measured_shift_arcsec']}\" vs predicted "
          f"{info['target']['predicted_shift_arcsec']}\" over {info['target']['dt_days']} d; "
          f"neighbours n={len(shifts)} median shift {info['neighbours']['median_shift_arcsec']}\"")
(OUT / f"{a.key}_phase1{sfx}.json").write_text(json.dumps(summary, indent=1, default=str))
print("visits per band:", {b: len(v["visits"]) for b, v in summary["bands"].items()})
