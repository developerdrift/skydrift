# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Phase 0 data proof for WISE 0855-0714.

Queries SPHEREx exposures (all six detectors), dedupes releases, clusters visits,
downloads cutouts in parallel (cached), measures the wavelength at the target per
exposure, writes a D6 contact sheet and co-moving D1-D6 stacks, and reports whether
WISE 0855 is detected.

Run:  .venv/Scripts/python probe.py
Out:  probe_out/  (PNGs + probe_results.json);  cache/probe/ (cutouts, gitignored)
"""
import json
import time
import warnings
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import requests
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.table import Table
from astropy.time import Time
from astropy.wcs import WCS, FITSFixedWarning
import astropy.units as u

warnings.filterwarnings("ignore", category=FITSFixedWarning)
warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "probe_out"
CACHE = ROOT / "cache" / "probe"
IRSA = "https://irsa.ipac.caltech.edu/"

CHALLENGE = SkyCoord("08h55m10.831s", "-07d14m42.53s")
# Fallback only if the CatWISE lookup fails (Luhman & Esplin 2016, arcsec/yr).
LIT_PM = (-8.118, 0.680)
CUTOUT_DEG = 0.06          # 3.6 arcmin: enough for a ~1 arcmin position error
GAP_DAYS = 30.0
MAX_WORKERS = 10


def tap(query, tries=4, timeout=180):
    """IRSA TAP sync with a hard timeout (astroquery's call can hang indefinitely)."""
    import io
    from astropy.io.votable import parse_single_table
    for i in range(tries):
        try:
            r = requests.post(f"{IRSA}TAP/sync", timeout=(15, timeout),
                              data=dict(LANG="ADQL", QUERY=query, FORMAT="votable"))
            r.raise_for_status()
            return parse_single_table(io.BytesIO(r.content)).to_table()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            wait = 10 * 2 ** i
            print(f"  TAP error ({type(e).__name__}), retry in {wait}s")
            time.sleep(wait)


def catwise_lookup():
    """Find WISE 0855 in CatWISE2020 (large PM, very red) near the challenge coords."""
    q = f"""SELECT source_name, ra, dec, pmra, pmdec, w1mpro, w2mpro, meanobsmjd
    FROM catwise_2020 WHERE 1=CONTAINS(POINT('ICRS',ra,dec),
    CIRCLE('ICRS',{CHALLENGE.ra.deg},{CHALLENGE.dec.deg},0.03))"""
    t = tap(q)
    t = t[np.hypot(t["pmra"].filled(0), t["pmdec"].filled(0)) > 3.0]
    if len(t) == 0:
        return None
    r = t[np.argmax(np.hypot(t["pmra"], t["pmdec"]))]
    return dict(name=str(r["source_name"]), ra=float(r["ra"]), dec=float(r["dec"]),
                pmra=float(r["pmra"]), pmdec=float(r["pmdec"]),
                w1=float(r["w1mpro"]) if r["w1mpro"] is not np.ma.masked else None,
                w2=float(r["w2mpro"]) if r["w2mpro"] is not np.ma.masked else None,
                mjd=float(r["meanobsmjd"]))


def propagate(ref, mjd):
    """Linear proper-motion propagation (arcsec/yr) from ref epoch to mjd."""
    dt = (mjd - ref["mjd"]) / 365.25
    dec = ref["dec"] + ref["pmdec"] * dt / 3600.0
    ra = ref["ra"] + ref["pmra"] * dt / 3600.0 / np.cos(np.radians(dec))
    return SkyCoord(ra * u.deg, dec * u.deg)


def query_exposures(coord):
    q = f"""SELECT p.obsid, p.planeid, p.datarelease, p.metarelease, p.energy_bandpassname,
      p.time_bounds_lower, p.time_bounds_upper, p.time_exposure,
      p.energy_bounds_lower, p.energy_bounds_upper, a.uri, a.producttype, a.releasetype
    FROM spherex.artifact a JOIN spherex.plane p ON a.planeid = p.planeid
    WHERE 1 = CONTAINS(POINT('ICRS', {coord.ra.deg}, {coord.dec.deg}), p.poly)
    ORDER BY p.time_bounds_lower"""
    return tap(q)


def release_rank(row):
    """Prefer DR1 over quick releases; among QRs prefer the highest number."""
    s = f"{row['datarelease']} {row['metarelease']}".upper()
    if "DR" in s:
        return 0
    digits = "".join(c for c in s if c.isdigit())
    return 100 - int(digits[:3] or 0)


def dedupe(t):
    best = {}
    for row in t:
        key = (str(row["obsid"]), str(row["energy_bandpassname"]))
        if key not in best or release_rank(row) < release_rank(best[key]):
            best[key] = row
    keep = sorted(best.values(), key=lambda r: r["time_bounds_lower"])
    return Table(rows=keep, names=t.colnames)


def cluster_visits(mjds, gap=GAP_DAYS):
    order = np.argsort(mjds)
    labels = np.empty(len(mjds), int)
    v = 0
    for k, i in enumerate(order):
        if k and mjds[i] - mjds[order[k - 1]] > gap:
            v += 1
        labels[i] = v
    return labels


def fetch_one(uri, coord, size, dest, tries=4):
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = f"{IRSA}{uri}?center={coord.ra.deg:.6f},{coord.dec.deg:.6f}d&size={size}"
    for i in range(tries):
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.replace(dest)
            return dest
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                return None
            time.sleep(3 * 2 ** i)


def flag_bit_names(hdr):
    names = {}
    for k, v in hdr.items():
        if k.startswith("MP_") or k.startswith("HIERARCH MP_"):
            try:
                names[int(v)] = k.replace("HIERARCH ", "")
            except (TypeError, ValueError):
                pass
    return names


def read_cutout(path, coord):
    with fits.open(path) as hl:
        img = hl["IMAGE"].data.astype(float)
        hdr = hl["IMAGE"].header
        flags = hl["FLAGS"].data.astype(np.int64)
        var = hl["VARIANCE"].data.astype(float)
        zodi = hl["ZODI"].data.astype(float)
        wcs = WCS(hdr)
        x, y = wcs.world_to_pixel(coord)
        try:
            swcs = WCS(hdr, fobj=hl, key="W")
            swcs.sip = None
            wav, bw = swcs.pixel_to_world(x, y)
            wav = float(u.Quantity(wav).to(u.um).value)
            bw = float(u.Quantity(bw).to(u.um).value)
        except Exception:  # noqa: BLE001
            wav, bw = np.nan, np.nan
        info = dict(bunit=hdr.get("BUNIT"), version=hl[0].header.get("VERSION"),
                    pixscale=float(np.mean(np.abs(wcs.proj_plane_pixel_scales())) * 3600 *
                                   (1 if wcs.wcs.cunit[0] in ("deg", "") else 1)),
                    bits=flag_bit_names(hl["FLAGS"].header))
    return dict(img=img, flags=flags, var=var, zodi=zodi, wcs=wcs, x=float(x), y=float(y),
                wav=wav, bw=bw, info=info)


def target_grid(coord, npix=61, scale_arcsec=3.0):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [coord.ra.deg, coord.dec.deg]
    w.wcs.crpix = [(npix + 1) / 2, (npix + 1) / 2]
    w.wcs.cdelt = [-scale_arcsec / 3600, scale_arcsec / 3600]
    return w, (npix, npix)


def comoving_stack(cuts, coords, mask_bits):
    """Inverse-variance stack, each exposure on a grid centred on its predicted position."""
    from reproject import reproject_interp
    num = den = None
    for c, coord in zip(cuts, coords):
        gw, shape = target_grid(coord)
        sci = c["img"] - c["zodi"]
        bad = (c["flags"] & mask_bits) != 0
        bad |= ~np.isfinite(sci) | ~np.isfinite(c["var"]) | (c["var"] <= 0)
        sci = np.where(bad, np.nan, sci)
        _, _, med = sigma_clipped_stats(sci[np.isfinite(sci)])
        sci -= med
        var = np.where(bad, np.nan, c["var"])
        s, _ = reproject_interp((sci, c["wcs"]), gw, shape_out=shape)
        v, _ = reproject_interp((var, c["wcs"]), gw, shape_out=shape)
        w = np.where(np.isfinite(s) & np.isfinite(v) & (v > 0), 1.0 / v, 0.0)
        s = np.nan_to_num(s)
        num = s * w if num is None else num + s * w
        den = w if den is None else den + w
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan), den


def detect_at_center(stack, rad_search=3, rad_ap=2.5):
    """Peak S/N near the grid centre plus aperture S/N, noise from the clipped field."""
    good = np.isfinite(stack)
    _, med, std = sigma_clipped_stats(stack[good], sigma=3)
    n = stack.shape[0]
    c = (n - 1) / 2
    yy, xx = np.mgrid[:n, :n]
    r = np.hypot(xx - c, yy - c)
    win = (r <= rad_search) & good
    k = np.argmax(np.where(win, stack, -np.inf))
    py, px = np.unravel_index(k, stack.shape)
    ap = (np.hypot(xx - px, yy - py) <= rad_ap) & good
    flux = np.nansum(stack[ap] - med)
    # Oversampled grid -> correlated noise; inflate by ~2 (2x oversample) to be honest.
    snr_ap = flux / (std * np.sqrt(ap.sum()) * 2.0)
    return dict(peak_snr=float((stack[py, px] - med) / std), ap_snr=float(snr_ap),
                offset_arcsec=float(np.hypot(px - c, py - c) * 3.0))


def asinh_png(arrays, path, titles, ncol=8, marks=True):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    vals = np.concatenate([a[np.isfinite(a)].ravel() for a in arrays])
    lo, hi = np.percentile(vals, [1, 99.7])
    nrow = int(np.ceil(len(arrays) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(1.9 * ncol, 2.1 * nrow), squeeze=False)
    for ax in axes.ravel():
        ax.axis("off")
    for ax, a, t in zip(axes.ravel(), arrays, titles):
        s = np.arcsinh((np.clip(a, lo, hi) - lo) / ((hi - lo) * 0.05))
        ax.imshow(s, origin="lower", cmap="gray")
        if marks:
            c = (a.shape[0] - 1) / 2
            ax.plot([c - 6, c - 3], [c, c], "r-", lw=0.8)
            ax.plot([c + 3, c + 6], [c, c], "r-", lw=0.8)
            ax.plot([c, c], [c - 6, c - 3], "r-", lw=0.8)
            ax.plot([c, c], [c + 3, c + 6], "r-", lw=0.8)
        ax.set_title(t, fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    OUT.mkdir(exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    res = {}

    print("1) CatWISE lookup for WISE 0855 ...")
    try:
        ref = catwise_lookup()
    except Exception as e:  # noqa: BLE001
        print("  CatWISE failed:", type(e).__name__)
        ref = None
    if ref is None:
        # Challenge coords treated as epoch 2010.5 (WISE) - flagged as an assumption.
        ref = dict(name="literature-fallback", ra=CHALLENGE.ra.deg, dec=CHALLENGE.dec.deg,
                   pmra=LIT_PM[0], pmdec=LIT_PM[1], mjd=Time(2010.5, format="jyear").mjd)
    res["reference"] = ref
    print(f"  ref {ref['name']} pm=({ref['pmra']:.2f},{ref['pmdec']:.2f})\"/yr "
          f"epoch MJD {ref['mjd']:.0f}")

    print("2) SPHEREx query (all detectors) ...")
    pos0 = propagate(ref, Time(2025.6, format="jyear").mjd)
    raw = query_exposures(pos0)
    res["raw_rows"] = len(raw)
    res["releases_raw"] = {k: v for k, v in Counter(
        f"{a}|{b}" for a, b in zip(raw["datarelease"], raw["metarelease"])).items()}
    res["producttypes"] = dict(Counter(str(x) for x in raw["producttype"]))
    t = dedupe(raw)
    res["deduped_rows"] = len(t)
    mjd = np.array(t["time_bounds_lower"], float)
    res["time_range_iso"] = [Time(mjd.min(), format="mjd").iso[:10],
                             Time(mjd.max(), format="mjd").iso[:10]]
    t["visit"] = cluster_visits(mjd)
    t["band"] = [str(b)[-2:] for b in t["energy_bandpassname"]]
    visits = {}
    for v in sorted(set(t["visit"])):
        m = mjd[t["visit"] == v]
        visits[int(v)] = dict(start=Time(m.min(), format="mjd").iso[:10],
                              end=Time(m.max(), format="mjd").iso[:10], n=int(len(m)))
    res["visits"] = visits
    res["counts"] = {b: {int(v): int(((t["band"] == b) & (t["visit"] == v)).sum())
                         for v in visits} for b in sorted(set(t["band"]))}
    print(f"  {len(raw)} rows -> {len(t)} after dedupe; {len(visits)} visits; "
          f"{res['time_range_iso']}")

    print("3) Cutouts ...")
    coords = [propagate(ref, m) for m in mjd]
    jobs = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for i, row in enumerate(t):
            dest = CACHE / f"{row['planeid']}_{CUTOUT_DEG}.fits"
            jobs[ex.submit(fetch_one, str(row["uri"]), coords[i], CUTOUT_DEG, dest)] = i
        paths = [None] * len(t)
        for f in as_completed(jobs):
            paths[jobs[f]] = f.result()
    ok = [i for i, p in enumerate(paths) if p is not None]
    res["cutouts_ok"], res["cutouts_failed"] = len(ok), len(t) - len(ok)
    print(f"  {len(ok)} ok, {len(t) - len(ok)} failed")

    cuts = {i: read_cutout(paths[i], coords[i]) for i in ok}
    first = cuts[ok[0]]["info"]
    res["image_units"], res["version"] = first["bunit"], first["version"]
    res["pixscale_arcsec"] = round(first["pixscale"], 3)
    res["flag_bits"] = {int(k): v for k, v in sorted(first["bits"].items())}

    # Mask hard-failure bits only, by name; informational bits are kept.
    hard = ("SATUR", "NONFUNC", "HOT", "COLD", "NAN", "DEAD", "TRANSIENT", "OVERFLOW",
            "NONLINEAR", "SUR_ERROR", "PHANTOM", "MISSING")
    mask_bits = 0
    for b, name in first["bits"].items():
        if any(h in name.upper() for h in hard):
            mask_bits |= 1 << b
    if not first["bits"]:
        mask_bits = ~0  # unknown meanings: mask every flagged pixel
    res["mask_bits"] = int(mask_bits) if mask_bits >= 0 else "all"

    wl = {}
    for b in sorted(set(t["band"])):
        w = [cuts[i]["wav"] for i in ok if t["band"][i] == b and np.isfinite(cuts[i]["wav"])]
        if w:
            wl[b] = dict(min=round(min(w), 3), max=round(max(w), 3), n=len(w),
                         n_distinct_0p01=len(set(np.round(w, 2))))
    res["wavelength_um"] = wl
    rows = [dict(planeid=str(t["planeid"][i]), band=str(t["band"][i]),
                 mjd=float(mjd[i]), visit=int(t["visit"][i]),
                 wav_um=cuts[i]["wav"], bw_um=cuts[i]["bw"]) for i in ok]
    Table(rows=rows).write(OUT / "exposures.csv", overwrite=True)

    print("4) D6 contact sheet + stacks ...")
    d6 = [i for i in ok if t["band"][i] == "D6"]
    from reproject import reproject_interp
    sheet, titles = [], []
    for i in d6[:64]:
        c = cuts[i]
        gw, shape = target_grid(coords[i])
        s, _ = reproject_interp((c["img"] - c["zodi"], c["wcs"]), gw, shape_out=shape)
        sheet.append(s - np.nanmedian(s))
        titles.append(f"{Time(mjd[i], format='mjd').iso[:10]} {c['wav']:.2f}um")
    if sheet:
        asinh_png(sheet, OUT / "w0855_d6_contact.png", titles)

    det = {}
    stacks, stitles = [], []
    for b in sorted(set(t["band"])):
        idx = [i for i in ok if t["band"][i] == b]
        if not idx:
            continue
        st, _ = comoving_stack([cuts[i] for i in idx], [coords[i] for i in idx], mask_bits)
        np.save(OUT / f"w0855_stack_{b}.npy", st)
        det[b] = detect_at_center(st) | {"n": len(idx)}
        stacks.append(st)
        stitles.append(f"{b} n={len(idx)} S/N={det[b]['ap_snr']:.1f}")
    res["detection"] = det
    if stacks:
        # Each band on its own stretch: absolute levels differ across 0.75-5 um.
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, len(stacks), figsize=(2.3 * len(stacks), 2.6))
        for ax, a, ti in zip(np.atleast_1d(axes), stacks, stitles):
            lo, hi = np.nanpercentile(a, [1, 99.7])
            ax.imshow(np.arcsinh((np.clip(a, lo, hi) - lo) / ((hi - lo) * 0.05)),
                      origin="lower", cmap="gray")
            ax.axis("off")
            ax.set_title(ti, fontsize=8)
            cc = (a.shape[0] - 1) / 2
            ax.plot(cc, cc, marker="+", color="r", ms=14, mew=0.6, alpha=0.6)
        fig.tight_layout()
        fig.savefig(OUT / "w0855_stacks_D1-D6.png", dpi=120)
        plt.close(fig)
    d6det = det.get("D6", {})
    res["detected_D6"] = bool(d6det and d6det["ap_snr"] >= 5 and d6det["offset_arcsec"] <= 6)
    (OUT / "probe_results.json").write_text(json.dumps(res, indent=1, default=str))
    print("  D6 detection:", res["detected_D6"], d6det)
    print("done ->", OUT)


if __name__ == "__main__":
    main()
