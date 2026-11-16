# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Glue: exposures -> calibrated, regridded frames -> per-visit stacks -> blink GIF."""
from pathlib import Path

import numpy as np
from astropy.time import Time

from . import calibrate, fetch, regrid, render, stack


def build_frames(records, ra, dec, fov_arcmin, scale_arcsec=regrid.NATIVE_ARCSEC / 2,
                 mask_bits=None):
    """records: dicts with path, band, visit, mjd, planeid, release. Skips unreadable files."""
    w_out, shape = regrid.target_wcs(ra, dec, fov_arcmin, scale_arcsec)
    frames = []
    for r in records:
        if r.get("path") is None:
            continue
        try:
            c = calibrate.load(r["path"])
        except Exception:  # noqa: BLE001
            continue
        sci, var, info = calibrate.calibrate(c, mask_bits)
        s, v = regrid.regrid(sci, var, c.wcs, w_out, shape)
        if not np.isfinite(s).any():
            continue
        wav, bw = calibrate.wavelength_at(r["path"], ra, dec)
        frames.append(dict(r, sci=s, var=v, wav=wav, bw=bw, **info))
    return frames, w_out


def visit_label(s, t0):
    date = Time(s["mjd_mean"], format="mjd").iso[:10]
    lo, hi = s["wav_range"]
    wl = f"{lo:.2f}-{hi:.2f}um" if np.isfinite(lo) else "wav n/a"
    return f"{s['band']} {date} +{s['mjd_mean'] - t0:.0f}d n={s['n']} {wl}"


def visit_blink(frames, band, out_gif=None, label_prefix=""):
    fs = [f for f in frames if f["band"] == band]
    if not fs:
        return None
    stacks = stack.group_stacks(fs)
    t0 = stacks[0]["mjd_mean"]
    st = render.shared_stretch([s["img"] for s in stacks])
    labels = [label_prefix + visit_label(s, t0) for s in stacks]
    if out_gif:
        render.write_gif([s["img"] for s in stacks], labels, out_gif, st)
    return dict(stacks=stacks, stretch=st, labels=labels)


def run_target(ra, dec, fov_arcmin, root, bands=None, out_dir=None, progress=None):
    """Live path: TAP query -> cutouts (cached) -> frames -> one visit-blink GIF per band."""
    size_deg = round(fov_arcmin / 60.0 * 1.15, 4)  # margin so rotation never clips corners
    t = fetch.find_exposures(ra, dec, size_deg, root, bands)
    paths = fetch.fetch_cutouts(t, ra, dec, size_deg, root, progress=progress)
    records = [dict(path=p, band=str(r["band"]), visit=int(r["visit"]), mjd=float(r["mjd"]),
                    planeid=str(r["planeid"]), obsid=str(r["obsid"]), release=str(r["release"]))
               for r, p in zip(t, paths)]
    frames, w = build_frames(records, ra, dec, fov_arcmin)
    out = {}
    for b in sorted({f["band"] for f in frames}):
        gif = Path(out_dir) / f"blink_{b}.gif" if out_dir else None
        out[b] = visit_blink(frames, b, gif)
    return dict(table=t, frames=frames, wcs=w, blinks=out,
                n_failed=sum(p is None for p in paths), query_source=t.meta.get("source"))
