# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Phase 3C truth check: measure known high-proper-motion stars with the SkyDrift pipeline and
compare first-to-last-visit displacement with the literature prediction (PM + parallax).

Usage: python scripts/truth_check.py
Writes app/static/validation/truth.json and truth_plot.png (served at /validation, copied to docs/).
Comparison values are LITERATURE values quoted from memory (engine/truthstars.py), not live Gaia.
"""
import json
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
import astropy  # noqa: E402,F401
import logging  # noqa: E402
logging.getLogger("astropy").setLevel(logging.ERROR)
import numpy as np  # noqa: E402
import astropy.units as u  # noqa: E402
from astropy.coordinates import GCRS, SkyCoord  # noqa: E402
from astropy.time import Time  # noqa: E402
from engine import candidates, fetch, pipeline, regrid, stack, views  # noqa: E402
from engine.targets import TARGETS, position_at  # noqa: E402
from engine.truthstars import stars  # noqa: E402

OUT = ROOT / "app" / "static" / "validation"
OUT.mkdir(parents=True, exist_ok=True)
CACHE = ROOT / "cache"
FOV = 8.0   # wide enough for >= 4 reference stars around a bright target
SCALE = regrid.NATIVE_ARCSEC / 2
PLX = {"barnard": 0.5470, "eps_indi_b": 0.2726, "wise0855": 0.449}
from engine.calibrate import DEFAULT_MASK, FLAG_BITS  # noqa: E402
# Saturated-star tier: the documented mask minus the saturation-related bits, so a saturated
# core keeps values to centroid on. Reported separately from the unsaturated measurements.
SAT_MASK = DEFAULT_MASK
for _b, _n in FLAG_BITS.items():
    if _n in ("OVERFLOW", "BLOOM", "SUR_ERROR", "TRANSIENT"):
        SAT_MASK &= ~(1 << _b)


def apparent(s, mjd):
    """ICRS position at mjd from PM, plus the annual parallax offset seen from Earth.
    Parallax offset = GCRS(star at its distance) - GCRS(same direction at infinity), so the
    aberration common to the whole field cancels (the field-offset step removes it anyway)."""
    t = Time(mjd, format="mjd")
    c = SkyCoord(s["ra"] * u.deg, s["dec"] * u.deg, distance=(1.0 / s["plx"]) * u.pc,
                 pm_ra_cosdec=s["pmra"] * u.arcsec / u.yr, pm_dec=s["pmdec"] * u.arcsec / u.yr,
                 radial_velocity=0 * u.km / u.s, obstime=Time(s["epoch"], format="jyear"))
    c2 = c.apply_space_motion(new_obstime=t)
    near = SkyCoord(c2.ra, c2.dec, distance=c2.distance).transform_to(GCRS(obstime=t))
    far = SkyCoord(c2.ra, c2.dec).transform_to(GCRS(obstime=t))
    dlon, dlat = far.spherical_offsets_to(near)
    return SkyCoord(c2.ra, c2.dec).spherical_offsets_by(dlon, dlat)


def measure(s):
    # Field centre: PM-only position at 2025.9 (same as the daemon's prefetch, so caches match).
    ra, dec = position_at(s, Time(2025.9, format="jyear").mjd)
    ra, dec = round(ra, 5), round(dec, 5)
    size = views.cutout_size(FOV)
    t = fetch.find_exposures(ra, dec, size, CACHE)
    if len(t) == 0:
        return [dict(star=s["name"], status="no coverage yet")]
    # Cap at 8 exposures per (detector, visit), evenly spaced: plenty for a position, and keeps
    # high-ecliptic-latitude stars (hundreds of exposures) from dominating the run.
    keep = []
    for key in sorted({(str(r["band"]), int(r["visit"])) for r in t}):
        idx = [i for i, r in enumerate(t) if (str(r["band"]), int(r["visit"])) == key]
        keep += [idx[j] for j in np.unique(np.linspace(0, len(idx) - 1, min(8, len(idx))).round().astype(int))]
    t = t[sorted(keep)]
    paths = fetch.fetch_cutouts(t, ra, dec, size, CACHE)
    recs = [dict(path=pp, band=str(r["band"]), visit=int(r["visit"]), mjd=float(r["mjd"]),
                 planeid=str(r["planeid"]), obsid=str(r["obsid"]), release=str(r["release"]))
            for r, pp in zip(t, paths)]
    frames, w = pipeline.build_frames(recs, ra, dec, FOV)
    sat_frames = None
    rows = []
    for band in sorted({f["band"] for f in frames}):
        st = stack.group_stacks([f for f in frames if f["band"] == band])
        if len(st) < 2:
            continue
        row = measure_band(s, st, w, band)
        if row["status"] != "measured" and "not detected" in row["status"]:
            # Tier 2: saturated core. Keep the saturation flags so the core has values.
            if sat_frames is None:
                sat_frames, _ = pipeline.build_frames(recs, ra, dec, FOV, mask_bits=SAT_MASK)
            st2 = stack.group_stacks([f for f in sat_frames if f["band"] == band])
            if len(st2) >= 2:
                row2 = measure_band(s, st2, w, band)
                if row2["status"] == "measured":
                    row = dict(row2, saturated=True)
        rows.append(row)
    return rows or [dict(star=s["name"], status="fewer than 2 visits in every detector")]


def measure_band(s, st, w, band):
    if True:
        pa_, pb_ = apparent(s, st[0]["mjd_mean"]), apparent(s, st[-1]["mjd_mean"])
        a = w.wcs_world2pix([[pa_.ra.deg, pa_.dec.deg]], 0)[0]
        b = w.wcs_world2pix([[pb_.ra.deg, pb_.dec.deg]], 0)[0]
        tgt = dict(name=s["name"], xy_first=a, xy_last=b, pm_note=s.get("note", "literature"),
                   pred_shift_arcsec=float(np.hypot(*(b - a)) * SCALE))
        cands, summ = candidates.find(st, w, SCALE, target=tgt)
        row = dict(star=s["name"], band=band, baseline_days=summ.get("baseline_days"),
                   n_matched=summ.get("n_matched"), field_scatter_arcsec=summ.get("field_scatter_arcsec"))
        k = [c for c in cands if c.get("known")]
        if summ.get("note") and not k:
            row["status"] = f"skipped: {summ['note']}"
        elif not k or k[0].get("shift_arcsec") is None:
            row["status"] = "not measured: not detected unsaturated in both visits"
        else:
            c = k[0]
            row.update(status="measured", matches_prediction=c["matches_prediction"], snr=c["snr"],
                       meas_shift=c["shift_arcsec"], pred_shift=c["pred_shift_arcsec"],
                       meas_en=c["meas_dxdy_arcsec"], pred_en=c["pred_dxdy_arcsec"], err_en=c["err_xy_arcsec"],
                       pa=c["pa_deg"], pred_pa=c["pred_pa_deg"], move_sigma=c["move_sigma"],
                       dipole=c.get("dipole_confirmed"))
        return row


def plot(m, summ):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 5), facecolor="#0b0d12")
    for ax in axes:
        ax.set_facecolor("#141821")
        for sp in ax.spines.values():
            sp.set_color("#555")
        ax.tick_params(colors="#ccc")
        ax.xaxis.label.set_color("#ccc")
        ax.yaxis.label.set_color("#ccc")
        ax.title.set_color("#eee")
    ax = axes[0]
    if m:
        mx = max(max(r["pred_shift"], r["meas_shift"]) for r in m) * 1.15 + 0.5
        ax.plot([0, mx], [0, mx], color="#7cc4ff", lw=1)
        for r in m:
            col = "#7cc4ff" if r["matches_prediction"] else "#ff8a8a"
            e = float(np.hypot(*r["err_en"]) / np.sqrt(2))
            ax.errorbar(r["pred_shift"], r["meas_shift"], yerr=e, fmt="o", color=col, ms=5, capsize=2,
                        mfc="none" if r.get("saturated") else col)
            ax.annotate(f"{r['star'].split(' (')[0]} {r['band']}", (r["pred_shift"], r["meas_shift"]),
                        fontsize=6, color="#aaa", xytext=(3, 3), textcoords="offset points")
        ax.set_xlim(0, mx)
        ax.set_ylim(0, mx)
    ax.set_xlabel("predicted first-to-last shift (arcsec)  [literature PM + parallax]")
    ax.set_ylabel("measured by SkyDrift (arcsec)")
    ru, ra_ = summ["unsaturated"]["rms_vector_residual_arcsec"], summ["rms_vector_residual_arcsec"]
    ax.set_title(f"{summ['n_measurements']} measurements, {summ['n_stars_measured']} stars. RMS: "
                 f"unsaturated {ru if ru is not None else '-'}\", all {ra_ if ra_ is not None else '-'}\"", fontsize=9)
    ax = axes[1]
    for r in m:
        d = np.subtract(r["meas_en"], r["pred_en"])
        col = "#7cc4ff" if r["matches_prediction"] else "#ff8a8a"
        ax.errorbar(d[0], d[1], xerr=r["err_en"][0], yerr=r["err_en"][1], fmt="o", color=col, ms=5, capsize=2,
                    mfc="none" if r.get("saturated") else col)
    lim = max(3.5, max((abs(v) for r in m for v in np.subtract(r["meas_en"], r["pred_en"])), default=0) * 1.1)
    ax.axhline(0, color="#555", lw=0.8)
    ax.axvline(0, color="#555", lw=0.8)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.set_xlabel("residual east (arcsec)")
    ax.set_ylabel("residual north (arcsec)")
    ax.set_title("measured minus predicted (SPHEREx pixel = 6.2\")", fontsize=10)
    fig.text(0.01, 0.01, "Filled: unsaturated; hollow: saturated core (saturation flags unmasked). Blue: consistent within 3 sigma; red: not. Comparison values are literature values "
             "quoted from memory, not live Gaia DR3 (IRSA TAP was down).", fontsize=7, color="#aaa")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(OUT / "truth_plot.png", dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    t0 = time.time()
    sample = stars()
    for key in ("barnard", "eps_indi_b", "wise0855"):
        tg = dict(TARGETS[key], plx=PLX[key])
        tg["name"] = tg["name"] + " (preset)"
        sample.append(tg)
    rows = []
    for s in sample:
        try:
            r = measure(s)
        except Exception as e:  # noqa: BLE001
            r = [dict(star=s["name"], status=f"error: {type(e).__name__}: {e}"[:200])]
        rows += r
        for x in r:
            extra = (f"  meas {x['meas_shift']:.2f}\" pred {x['pred_shift']:.2f}\" ok={x['matches_prediction']}"
                     if x["status"] == "measured" else "")
            print(f"{x['star']:24s} {x.get('band', '--')} {x['status']}{extra}", flush=True)
    # Prefer unsaturated: a star with any unsaturated measurement keeps only those; the
    # saturated-core tier is kept only for stars that have nothing unsaturated.
    unsat_stars = {r["star"] for r in rows if r["status"] == "measured" and not r.get("saturated")}
    for r in rows:
        if r["status"] == "measured" and r.get("saturated") and r["star"] in unsat_stars:
            r["status"] = "saturated-core measurement dropped (an unsaturated one exists for this star)"
    rows.sort(key=lambda r: (r["status"] != "measured", bool(r.get("saturated")), r["star"]))
    m = [r for r in rows if r["status"] == "measured"]
    good = [r for r in m if r["matches_prediction"]]

    def rms(rs):
        if not rs:
            return None
        d = np.array([np.subtract(r["meas_en"], r["pred_en"]) for r in rs])
        return round(float(np.sqrt(np.mean(np.sum(d ** 2, axis=1)))), 3)
    mu = [r for r in m if not r.get("saturated")]
    summary = dict(
        unsaturated=dict(n_measurements=len(mu), n_stars=len({r["star"] for r in mu}),
                         n_consistent=sum(r["matches_prediction"] for r in mu),
                         rms_vector_residual_arcsec=rms(mu),
                         rms_vector_residual_consistent_arcsec=rms([r for r in mu if r["matches_prediction"]])),
        generated=time.strftime("%Y-%m-%d %H:%M"), n_stars=len(sample),
        n_measurements=len(m), n_stars_measured=len({r["star"] for r in m}), n_consistent=len(good),
        rms_vector_residual_arcsec=rms(m), rms_vector_residual_consistent_arcsec=rms(good),
        caveats=["Comparison PMs/parallaxes are literature values quoted from memory, not live Gaia DR3 "
                 "(IRSA TAP down). A wrong catalogue value would show up as an outlier, so outliers are kept.",
                 "Coverage is partial (sampled S3 header scan), so most stars have only 2 visits.",
                 "Unsaturated measurements use the documented photometry mask. Stars that fail it because "
                 "their core is saturated are re-measured with only the saturation flags unmasked and "
                 "reported separately (hollow markers, 'saturated': true); their centroids are less reliable.",
                 "Known targets not extracted by source detection are measured with a forced windowed "
                 "centroid at the predicted position (S/N > 10 required)."],
        rows=rows, seconds=round(time.time() - t0, 1))
    (OUT / "truth.json").write_text(json.dumps(summary, indent=1, default=str))
    plot(m, summary)
    print(f"measured {len(m)} (stars {summary['n_stars_measured']}), consistent {len(good)}, "
          f"RMS all {summary['rms_vector_residual_arcsec']}, RMS consistent "
          f"{summary['rms_vector_residual_consistent_arcsec']}")


if __name__ == "__main__":
    main()
