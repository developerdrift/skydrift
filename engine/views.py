# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Build a 'view' for one sky position: everything the blink player needs, on disk.

Output dir: <root>/views/<ra>_<dec>_<fov>/
  manifest.json                      metadata for every band / mode / frame
  <band>_visits.f32 / _exp.f32 / _all.f32   float32 stacks, shape (n, H, W), row 0 = south
The browser does stretching, blinking and A-B subtraction itself, so the same files serve the
live app and the static showcase.
"""
import json
import time
from pathlib import Path

import numpy as np
from astropy.time import Time

from . import candidates, fetch, pipeline, regrid, render, spectrum, stack, targets

CUTOUT_SIZES = (0.12, 0.24, 0.6)   # quantised so nearby fovs share the cutout cache
VIEW_VERSION = 6   # 3: candidates + always-measured target


def cutout_size(fov_arcmin):
    need = fov_arcmin / 60.0 * 1.15
    for s in CUTOUT_SIZES:
        if s >= need:
            return s
    return round(need, 3)


def view_dir(root, ra, dec, fov):
    return Path(root) / "views" / f"{ra:.5f}_{dec:+.5f}_{fov:g}"


def _iso(mjd):
    return Time(mjd, format="mjd").isot[:16].replace("T", " ")


def _preset_target(ra, dec, w, stacks):
    """The preset's own star (literature PM) as seen on this grid, if this view is a preset."""
    for p in targets.preset_positions():
        if abs(p["ra"] - ra) < 1e-4 and abs(p["dec"] - dec) < 1e-4:
            t = targets.TARGETS[p["key"]]
            a = w.wcs_world2pix([targets.position_at(p["key"], stacks[0]["mjd_mean"])], 0)[0]
            b = w.wcs_world2pix([targets.position_at(p["key"], stacks[-1]["mjd_mean"])], 0)[0]
            return dict(name=t["name"], xy_first=a, xy_last=b,
                        pred_shift_arcsec=float(np.hypot(*(b - a)) * regrid.NATIVE_ARCSEC / 2),
                        pm_note="literature PM, not a live Gaia query")
    return None


def _write(path, arrs):
    np.stack(arrs).astype("<f4").tofile(path)


def build_view(ra, dec, fov, root, progress=None, force=False):
    """Return the manifest dict, building it (and fetching data) if needed."""
    out = view_dir(root, ra, dec, fov)
    mpath = out / "manifest.json"
    if mpath.exists() and not force:
        m = json.loads(mpath.read_text())
        if m.get("version") == VIEW_VERSION:
            return m
    out.mkdir(parents=True, exist_ok=True)
    prog = progress or (lambda stage, frac: None)
    t0 = time.time()
    size = cutout_size(fov)
    prog("finding exposures", 0.02)
    t = fetch.find_exposures(ra, dec, size, root, log=lambda m: prog(m.strip(), 0.05))
    prog(f"downloading {len(t)} cutouts", 0.1)
    paths = fetch.fetch_cutouts(t, ra, dec, size, root,
                                progress=lambda d, n: prog(f"cutouts {d}/{n}", 0.1 + 0.6 * d / max(n, 1)))
    recs = [dict(path=p, band=str(r["band"]), visit=int(r["visit"]), mjd=float(r["mjd"]),
                 planeid=str(r["planeid"]), obsid=str(r["obsid"]), release=str(r["release"]))
            for r, p in zip(t, paths)]
    prog("calibrating and reprojecting", 0.72)
    frames, w = pipeline.build_frames(recs, ra, dec, fov)
    h, wd = (frames[0]["sci"].shape if frames else regrid.target_wcs(ra, dec, fov)[1])
    man = dict(version=VIEW_VERSION, ra=ra, dec=dec, fov=fov, shape=[int(h), int(wd)],
               scale_arcsec=regrid.NATIVE_ARCSEC / 2, cutout_deg=size,
               source=t.meta.get("source"), n_found=len(t),
               n_failed=int(sum(p is None for p in paths)), built=time.strftime("%Y-%m-%d %H:%M"),
               bands={})
    if not frames:
        man["empty_reason"] = ("No SPHEREx exposures are indexed for this position yet. The background "
                               "scan has been asked to search here - try again in a few minutes.")
    for band in sorted({f["band"] for f in frames}):
        prog(f"stacking {band}", 0.8)
        fs = sorted([f for f in frames if f["band"] == band], key=lambda f: f["mjd"])
        visits = stack.group_stacks(fs)
        allst = stack.all_epoch(fs)
        t_first = fs[0]["mjd"]
        exp_meta = [dict(planeid=f["planeid"], obsid=f["obsid"], release=f["release"],
                         version=f.get("version"), time=_iso(f["mjd"]), mjd=round(f["mjd"], 5),
                         days=round(f["mjd"] - t_first, 2), visit=f["visit"],
                         wav=None if not np.isfinite(f["wav"]) else round(f["wav"], 4),
                         bw=None if not np.isfinite(f["bw"]) else round(f["bw"], 4),
                         flag_pct=round(100 * f["flag_frac_any"], 1),
                         masked_pct=round(100 * f["flag_frac_masked"], 1),
                         flag_bits=f["flag_bits_present"]) for f in fs]
        vis_meta = []
        for s in visits:
            members = [e for e in exp_meta if e["planeid"] in s["planeids"]]
            wl = [e["wav"] for e in members if e["wav"] is not None]
            vis_meta.append(dict(time=_iso(s["mjd_mean"]), mjd=round(s["mjd_mean"], 4),
                                 days=round(s["mjd_mean"] - visits[0]["mjd_mean"], 1),
                                 n=s["n"], wav=[min(wl), max(wl)] if wl else None,
                                 span=[_iso(s["mjd_range"][0]), _iso(s["mjd_range"][1])],
                                 obsids=[e["obsid"] for e in members],
                                 releases=sorted({e["release"] for e in members}),
                                 versions=sorted({str(e["version"]) for e in members}),
                                 flag_pct=round(float(np.mean([e["flag_pct"] for e in members])), 1),
                                 masked_pct=round(float(np.mean([e["masked_pct"] for e in members])), 1),
                                 flag_bits=sorted({b for e in members for b in e["flag_bits"]})))
        cands, csum = [], dict(note="needs >= 2 visits")
        if len(visits) >= 2:
            prog(f"finding candidates {band}", 0.85)
            cands, csum = candidates.find(visits, w, regrid.NATIVE_ARCSEC / 2,
                                          target=_preset_target(ra, dec, w, visits))
        _write(out / f"{band}_visits.f32", [s["img"] for s in visits])
        _write(out / f"{band}_exp.f32", [f["sci"] for f in fs])
        _write(out / f"{band}_all.f32", [allst["img"]])
        all_wl = [e["wav"] for e in exp_meta if e["wav"] is not None]
        man["bands"][band] = dict(
            visits=vis_meta, exposures=exp_meta,
            all=dict(n=len(fs), wav=[min(all_wl), max(all_wl)] if all_wl else None,
                     span=[exp_meta[0]["time"], exp_meta[-1]["time"]]),
            candidates=cands, cand_summary=csum,
            stretch=dict(visits=render.shared_stretch([s["img"] for s in visits]),
                         exp=render.shared_stretch([f["sci"] for f in fs]),
                         all=render.shared_stretch([allst["img"]])))
    # Precomputed spectra (for the static showcase): grid centre + each distinct candidate.
    prog("spectra", 0.92)
    man["spectra"] = []
    if man["bands"]:
        c = (int(h) - 1) / 2
        spots = [(c, c, "field centre")]
        for band, bd in man["bands"].items():
            for cd in bd.get("candidates", []):
                if cd.get("x") is not None and all(np.hypot(cd["x"] - x, cd["y"] - y) > 3 for x, y, _ in spots):
                    spots.append((cd["x"], cd["y"], f"{band} {cd['kind']}"))
        for x, y, lab in spots[:10]:
            try:
                fol, snapped = spectrum.follow_for(man, x, y, w)
                sp = spectrum.spectrum(man, root, fol)
                man["spectra"].append(dict(sp, x=round(float(x), 2), y=round(float(y), 2), label=lab,
                                           snapped=snapped.get("kind") if snapped else None))
            except Exception:  # noqa: BLE001
                pass
    man["seconds"] = round(time.time() - t0, 1)
    mpath.write_text(json.dumps(man, default=str))
    prog("done", 1.0)
    return man


def ensure_fresh(ra, dec, fov, root, progress=None):
    """Build the view, or rebuild it if the coverage index now has more exposures than the
    manifest was built from (so derived results - stacks, candidates - track the data)."""
    mp = view_dir(root, ra, dec, fov) / "manifest.json"
    stale = False
    if mp.exists():
        man = json.loads(mp.read_text())
        now = len(fetch.find_exposures(ra, dec, cutout_size(fov), root))
        stale = man.get("version") != VIEW_VERSION or now > man.get("n_found", 0)
    return build_view(ra, dec, fov, root, progress=progress, force=stale)
