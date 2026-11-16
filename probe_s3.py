# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Phase 0 data proof for WISE 0855, S3 fallback path (IRSA TAP/SIA down on 2026-11-15).

Input: cache/s3index/wise0855_covering.json from scripts/find_exposures_s3.py.
NOTE: that list is PARTIAL coverage from sparse header sampling; a full scan has not been run.

Reference epoch of the challenge coordinates could not be verified (CatWISE via IRSA TAP and
SIMBAD were both unreachable), so two hypotheses are tested and reported side by side:
  A: challenge coords at the WISE epoch (~2010.5)    B: challenge coords at J2000.0
Proper motion: Luhman & Esplin 2016 values (-8.118, +0.680) arcsec/yr, quoted from memory,
not verified this session. Parallax (~0.45") is ignored (0.15 px on the 3.1"/px grid).

FLAGS: the real FLAGS header has no bit names, so ANY nonzero flag is masked. No bit
meanings are assumed.

Run:  .venv/Scripts/python probe_s3.py
Out:  probe_out/ (w0855_*.png, probe_s3_results.json, exposures_s3.csv)
"""
import json
import sys
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.stats import sigma_clipped_stats
from astropy.table import Table
from astropy.time import Time
import astropy.units as u

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from engine import calibrate, fetch, regrid, stack  # noqa: E402
from engine.s3scan import NAME_RE  # noqa: E402

warnings.filterwarnings("ignore")
OUT = ROOT / "probe_out"
CACHE = ROOT / "cache"
CHALLENGE = SkyCoord("08h55m10.831s", "-07d14m42.53s")
PM = (-8.118, 0.680)                       # arcsec/yr, Luhman & Esplin 2016 (unverified here)
HYP = {"A_epoch2010.5": Time(2010.5, format="jyear").mjd, "B_J2000": Time(2000.0, format="jyear").mjd}
SIZE_DEG = 0.12
FOV_ARCMIN = 6.0
SCALE = regrid.NATIVE_ARCSEC / 2
MASK_ANY = -1                              # mask every nonzero FLAGS value
DIAG_LABEL = ("DIAGNOSTIC - bit 21 unmasked because it is set in 100% of exposures at this position "
              "and covers ~44% of all pixels uniformly, which is inconsistent with it marking a real "
              "per-pixel defect. Meaning not confirmed - treat this detection result as provisional.")
AP_R, SEARCH_R = 3.0, 2.0                  # grid pixels (3.1"/px)


def predict(ref_mjd, mjd):
    dt = (mjd - ref_mjd) / 365.25
    dec = CHALLENGE.dec.deg + PM[1] * dt / 3600
    ra = CHALLENGE.ra.deg + PM[0] * dt / 3600 / np.cos(np.radians(dec))
    return ra, dec


def phot(img, x0, y0, rng, n_null=400):
    """Peak-search within SEARCH_R of (x0,y0), aperture sum there. Noise from the same
    procedure at random empty positions (fair null), sigma-clipped."""
    ny, nx = img.shape
    yy, xx = np.mgrid[:ny, :nx]

    def measure(x, y):
        win = (np.hypot(xx - x, yy - y) <= SEARCH_R) & np.isfinite(img)
        if not win.any():
            return np.nan, x, y
        k = np.argmax(np.where(win, img, -np.inf))
        py, px = np.unravel_index(k, img.shape)
        ap = np.hypot(xx - px, yy - py) <= AP_R
        if not np.isfinite(img[ap]).all():
            return np.nan, px, py
        return float(img[ap].sum()), px, py

    f, px, py = measure(x0, y0)
    sums = []
    m = AP_R + SEARCH_R + 2
    while len(sums) < n_null:
        x, y = rng.uniform(m, nx - m), rng.uniform(m, ny - m)
        if np.hypot(x - x0, y - y0) < 12:
            continue
        s, _, _ = measure(x, y)
        if np.isfinite(s):
            sums.append(s)
        if len(sums) == 0 and rng.random() < 0.001:
            break
    mean, med, std = sigma_clipped_stats(np.array(sums), sigma=3)
    snr = (f - med) / std if np.isfinite(f) and std > 0 else np.nan
    return dict(snr=float(snr), flux=float(f - med), noise=float(std),
                offset_arcsec=float(np.hypot(px - x0, py - y0) * SCALE), x=int(px), y=int(py))


def show(ax, img, title, marks):
    lo, hi = np.nanpercentile(img, [1, 99.5])
    ax.imshow(np.arcsinh((np.clip(img, lo, hi) - lo) / ((hi - lo) * 0.05)), origin="lower",
              cmap="gray")
    for (x, y), col in marks:
        ax.add_patch(__import__("matplotlib").patches.Circle((x, y), 5, fill=False, ec=col, lw=0.8))
    ax.set_title(title, fontsize=7)
    ax.set_xticks([])
    ax.set_yticks([])


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--unmask-bit", type=int, action="append", default=[],
                    help="DIAGNOSTIC: leave this FLAGS bit unmasked (repeatable)")
    args = ap.parse_args()
    mask_bits = MASK_ANY
    for b in args.unmask_bit:
        mask_bits &= ~(1 << b)
    sfx = "".join(f"_diag_unmask_bit{b}" for b in args.unmask_bit)
    label = DIAG_LABEL if args.unmask_bit == [21] else (f"DIAGNOSTIC - bits {args.unmask_bit} unmasked" if args.unmask_bit else "")
    OUT.mkdir(exist_ok=True)
    cov = json.loads((CACHE / "s3index" / "wise0855_covering.json").read_text())["covering"]
    mjd_mid = np.mean([r["mjd"] for r in cov])
    pa = predict(HYP["A_epoch2010.5"], mjd_mid)
    pb = predict(HYP["B_J2000"], mjd_mid)
    cra, cdec = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2

    rows = []
    for r in cov:
        m = NAME_RE.search(r["key"])
        rows.append(dict(planeid=Path(r["key"]).stem, uri="ibe/data/spherex/" + r["key"],
                         release="dr1", band=f"D{r['det']}", mjd=float(r["mjd"]),
                         period=m["period"], seq=int(m["seq"]), exp=int(m["exp"])))
    t = Table(rows=rows)
    t["visit"] = fetch.cluster_visits(t["mjd"])
    print(f"fetching {len(t)} cutouts ({SIZE_DEG} deg) ...")
    paths = fetch.fetch_cutouts(t, cra, cdec, SIZE_DEG, CACHE)
    print(f"  ok {sum(p is not None for p in paths)}, failed {sum(p is None for p in paths)}")

    w_out, shape = regrid.target_wcs(cra, cdec, FOV_ARCMIN, SCALE)
    frames, exp_rows = [], []
    for row, p in zip(t, paths):
        if p is None:
            continue
        c = calibrate.load(p)
        sci, var, info = calibrate.calibrate(c, mask_bits=mask_bits)
        s, v = regrid.regrid(sci, var, c.wcs, w_out, shape)
        ra_a, dec_a = predict(HYP["A_epoch2010.5"], row["mjd"])
        wav, bw = calibrate.wavelength_at(p, ra_a, dec_a)
        # is the target's own native pixel flagged in this exposure? (hypothesis A position)
        xa, ya = c.wcs.world_to_pixel(SkyCoord(ra_a * u.deg, dec_a * u.deg))
        ix, iy = int(round(float(xa))), int(round(float(ya)))
        tgt_flag = int(c.flags[iy, ix]) if 0 <= iy < c.flags.shape[0] and 0 <= ix < c.flags.shape[1] else -1
        frames.append(dict(sci=s, var=v, band=row["band"], visit=int(row["visit"]),
                           mjd=row["mjd"], wav=wav, planeid=row["planeid"]))
        exp_rows.append(dict(planeid=row["planeid"], band=row["band"], visit=int(row["visit"]),
                             date=Time(row["mjd"], format="mjd").isot[:19], mjd=round(row["mjd"], 5),
                             wav_um=round(wav, 4), bw_um=round(bw, 4),
                             flag_frac=round(info["flag_frac_any"], 3),
                             target_pix_flag=tgt_flag, version=info["version"], bunit=info["bunit"]))
    Table(rows=exp_rows).write(OUT / f"exposures_s3{sfx}.csv", overwrite=True)

    res = dict(note="PARTIAL coverage from sparse header sampling - full scan not yet run",
               diagnostic=label or None, mask_rule=("any nonzero FLAGS masked" + (f" EXCEPT bits {args.unmask_bit}" if args.unmask_bit else "")),
               data_path="S3 header scan + IRSA cutout service (TAP/SIA down)",
               pm_arcsec_yr=PM, pm_source="Luhman & Esplin 2016, from memory, unverified",
               hypotheses={k: Time(v, format="mjd").jyear for k, v in HYP.items()},
               cutout_centre=[cra, cdec], n_exposures=len(exp_rows),
               counts={b: dict(Counter(str(e["visit"]) for e in exp_rows if e["band"] == b))
                       for b in sorted({e["band"] for e in exp_rows})})
    visits = {}
    for e in exp_rows:
        v = visits.setdefault(e["visit"], dict(dates=set(), bands=set()))
        v["dates"].add(e["date"][:10])
        v["bands"].add(e["band"])
    res["visits"] = {k: dict(dates=sorted(v["dates"]), bands=sorted(v["bands"])) for k, v in sorted(visits.items())}
    res["wavelength_um"] = {b: [e["wav_um"] for e in exp_rows if e["band"] == b] for b in res["counts"]}
    res["flag_frac_any_mean"] = round(float(np.mean([e["flag_frac"] for e in exp_rows])), 3)
    res["target_pixel_flagged"] = sum(e["target_pix_flag"] not in (0, -1) for e in exp_rows)

    # stacks per band (each band falls in a single visit here) and photometry for A and B
    rng = np.random.default_rng(42)
    det, stacks = {}, {}
    for b in sorted({f["band"] for f in frames}):
        fs = [f for f in frames if f["band"] == b]
        img, var, nmap = stack.ivw([f["sci"] for f in fs], [f["var"] for f in fs])
        stacks[b] = img
        np.save(OUT / f"w0855_stack_{b}{sfx}.npy", img)
        m = np.mean([f["mjd"] for f in fs])
        det[b] = dict(n=len(fs), date=Time(m, format="mjd").iso[:10])
        for h, ref in HYP.items():
            x, y = w_out.wcs_world2pix([predict(ref, m)], 0)[0]
            det[b][h] = phot(img, x, y, rng) | dict(n_cover_at_target=int(nmap[int(round(y)), int(round(x))]))
    res["detection"] = det
    d6 = det.get("D6", {})
    res["detected_D6"] = {h: bool(d6 and d6[h]["snr"] >= 5 and d6[h]["offset_arcsec"] <= 6.5) for h in HYP}

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def marks_for(mjd):
        return [(tuple(w_out.wcs_world2pix([predict(HYP["A_epoch2010.5"], mjd)], 0)[0]), "lime"),
                (tuple(w_out.wcs_world2pix([predict(HYP["B_J2000"], mjd)], 0)[0]), "orange")]

    d6f = sorted([f for f in frames if f["band"] == "D6"], key=lambda f: f["mjd"])
    if d6f:
        fig, axes = plt.subplots(1, len(d6f) + 1, figsize=(2.6 * (len(d6f) + 1), 3.0))
        for ax, f in zip(axes, d6f):
            show(ax, f["sci"], f"{Time(f['mjd'], format='mjd').isot[:16]}\n{f['wav']:.3f} um", marks_for(f["mjd"]))
        show(axes[-1], stacks["D6"], f"D6 stack n={len(d6f)}\nS/N A={d6['A_epoch2010.5']['snr']:.1f} B={d6['B_J2000']['snr']:.1f}",
             marks_for(np.mean([f["mjd"] for f in d6f])))
        fig.suptitle(("[DIAGNOSTIC: bit 21 unmasked, provisional] " if sfx else "") + "WISE 0855 - SPHEREx D6 exposures (real data, DR1). green=A (2010.5 ref), orange=B (J2000 ref). N up, E left",
                     fontsize=8)
        fig.tight_layout()
        fig.savefig(OUT / f"w0855_d6_contact{sfx}.png", dpi=120)
        plt.close(fig)

    bands = sorted(stacks)
    fig, axes = plt.subplots(1, len(bands), figsize=(2.5 * len(bands), 3.0))
    for ax, b in zip(np.atleast_1d(axes), bands):
        d = det[b]
        show(ax, stacks[b], f"{b} {d['date']} n={d['n']}\nS/N A={d['A_epoch2010.5']['snr']:.1f} B={d['B_J2000']['snr']:.1f}",
             marks_for(Time(d["date"]).mjd))
    fig.suptitle(("[DIAGNOSTIC: bit 21 unmasked, provisional] " if sfx else "") + "WISE 0855 per-detector stacks (real data; each band has a single visit here)", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / f"w0855_stacks_D1-D6{sfx}.png", dpi=120)
    plt.close(fig)

    (OUT / f"probe_s3_results{sfx}.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(dict(counts=res["counts"], visits=res["visits"], flag=res["flag_frac_any_mean"],
                          tgt_flagged=res["target_pixel_flagged"], detected_D6=res["detected_D6"]), default=str))
    for b in bands:
        print(b, det[b]["date"], "n", det[b]["n"], " ".join(
            f"{h[:1]}: snr={det[b][h]['snr']:.1f} off={det[b][h]['offset_arcsec']:.1f}\" cov={det[b][h]['n_cover_at_target']}"
            for h in HYP))
    print("wavelengths:", {b: (min(v), max(v)) for b, v in res["wavelength_um"].items()})


if __name__ == "__main__":
    main()
