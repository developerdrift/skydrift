# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Spectrum on click: forced aperture photometry at one sky position on every exposure.

- Every exposure of the view (all six detectors) is measured at the source position for that
  exposure's time. If the source moves, the position follows a linear track between its
  first- and last-visit positions (from the candidate measurement); otherwise it is fixed.
- Flux: IMAGE - ZODI, local background (median of an annulus) removed, summed in a circular
  aperture, converted from MJy/sr to microjansky with each cutout's pixel solid angle.
  Error: sqrt(sum VARIANCE) in the same units (background noise not added).
- Wavelength/bandwidth: from the exposure's spectral WCS at that pixel (IRSA recipe).
- 'flagged' = any aperture pixel carries a flag from the documented photometry mask list.
"""
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u

from . import calibrate, fetch

AP_R = 2.0          # native pixels (~12")
ANN = (4.0, 7.0)    # background annulus, native pixels
BANDS_UM = {"D1": (0.75, 1.09), "D2": (1.10, 1.62), "D3": (1.63, 2.41),
            "D4": (2.42, 3.82), "D5": (3.83, 4.41), "D6": (4.42, 5.00)}


def _measure(path, ra, dec):
    with fits.open(path) as hl:
        h = hl["IMAGE"].header
        w = WCS(h)
        img = hl["IMAGE"].data.astype(float) - hl["ZODI"].data.astype(float)
        var = hl["VARIANCE"].data.astype(float)
        flags = hl["FLAGS"].data.astype(np.int64)
    x, y = w.world_to_pixel(SkyCoord(ra * u.deg, dec * u.deg))
    x, y = float(x), float(y)
    ny, nx = img.shape
    if not (AP_R < x < nx - 1 - AP_R and AP_R < y < ny - 1 - AP_R):
        return None
    yy, xx = np.mgrid[:ny, :nx]
    r = np.hypot(xx - x, yy - y)
    ap = r <= AP_R
    ann = (r >= ANN[0]) & (r <= ANN[1]) & np.isfinite(img) & ((flags & calibrate.DEFAULT_MASK) == 0)
    if ann.sum() < 8 or not np.isfinite(img[ap]).all():
        return None
    bkg = float(np.median(img[ann]))
    omega = float(w.proj_plane_pixel_area().to(u.sr).value)      # sr per pixel
    to_ujy = omega * 1e12                                        # MJy -> uJy
    flux = float((img[ap] - bkg).sum()) * to_ujy
    err = float(np.sqrt(np.nansum(var[ap]))) * to_ujy
    fl = int(np.bitwise_or.reduce(flags[ap].ravel()))
    bad = fl & calibrate.DEFAULT_MASK
    names = [calibrate.FLAG_BITS.get(b, f"bit{b}") for b in range(32) if bad >> b & 1]
    wav, bw = calibrate.wavelength_at(path, ra, dec)
    return dict(flux=flux, err=err, wav=wav, bw=bw, flagged=bool(bad), flags=names)


def track(follow, mjd):
    """Position at mjd: fixed, or linear between (mjd0, ra0, dec0) and (mjd1, ra1, dec1)."""
    if not follow or follow.get("mjd1") is None or follow["mjd1"] == follow["mjd0"]:
        return follow["ra"], follow["dec"]
    f = (mjd - follow["mjd0"]) / (follow["mjd1"] - follow["mjd0"])
    return (follow["ra0"] + f * (follow["ra1"] - follow["ra0"]),
            follow["dec0"] + f * (follow["dec1"] - follow["dec0"]))


def spectrum(man, root, follow):
    """man: a view manifest; follow: dict(ra, dec[, ra0, dec0, mjd0, ra1, dec1, mjd1])."""
    pts = []
    for band, bd in man["bands"].items():
        for e in bd["exposures"]:
            p = fetch.cutout_dest(root, man["ra"], man["dec"], man["cutout_deg"], e["release"], e["planeid"])
            if not p.exists():
                continue
            ra, dec = track(follow, e["mjd"])
            try:
                m = _measure(p, ra, dec)
            except Exception:  # noqa: BLE001
                m = None
            if m is None or not np.isfinite(m["flux"]):
                continue
            pts.append(dict(band=band, visit=e["visit"], mjd=e["mjd"], time=e["time"],
                            wav=None if not np.isfinite(m["wav"]) else round(m["wav"], 4),
                            bw=None if not np.isfinite(m["bw"]) else round(m["bw"], 4),
                            flux=round(m["flux"], 3), err=round(m["err"], 3),
                            flagged=m["flagged"], flags=m["flags"], obsid=e["obsid"]))
    # per-visit light curve: inverse-variance mean of unflagged points per (band, visit)
    lc = []
    for band in sorted({p["band"] for p in pts}):
        for v in sorted({p["visit"] for p in pts if p["band"] == band}):
            q = [p for p in pts if p["band"] == band and p["visit"] == v and not p["flagged"] and p["err"] > 0]
            if not q:
                continue
            wts = np.array([1 / p["err"] ** 2 for p in q])
            f = float(np.sum(wts * [p["flux"] for p in q]) / wts.sum())
            wl = [p["wav"] for p in q if p["wav"]]
            lc.append(dict(band=band, visit=v, mjd=round(float(np.mean([p["mjd"] for p in q])), 3),
                           flux=round(f, 3), err=round(float(1 / np.sqrt(wts.sum())), 3), n=len(q),
                           wav=[min(wl), max(wl)] if wl else None))
    return dict(ra=round(follow["ra"], 6), dec=round(follow["dec"], 6), aperture_arcsec=round(AP_R * 6.2, 1),
                note="Forced photometry in a 12\" aperture: any source within ~15\" blends into these points.",
                moving=bool(follow.get("mjd1")), points=pts, lightcurve=lc,
                units="microjansky (uJy); aperture r=2 native px; local background removed")


def follow_for(man, x, y, wgrid, max_px=4.0):
    """Clicked grid pixel -> follow spec. Snaps to the nearest candidate (in any band) within
    max_px and uses its measured first/last-visit positions if it moved."""
    best = None
    for band, bd in man["bands"].items():
        for c in bd.get("candidates", []):
            if c.get("x") is None:
                continue
            d = float(np.hypot(c["x"] - x, c["y"] - y))
            # prefer candidates whose motion is confirmed (matches prediction or dipole); a
            # 'near target (not matched)' or unconfirmed entry only wins if nothing better is near
            trusted = c.get("matches_prediction") or c.get("dipole_confirmed") or c.get("kind") == "variable"
            rank = d + (0.0 if trusted else max_px)
            if d < max_px and (best is None or rank < best[0]):
                best = (rank, band, c)
    if best is None:
        ra, dec = wgrid.wcs_pix2world([[x, y]], 0)[0]
        return dict(ra=float(ra), dec=float(dec)), None
    _, band, c = best
    ra1, dec1 = wgrid.wcs_pix2world([[c["x"], c["y"]]], 0)[0]
    out = dict(ra=float(ra1), dec=float(dec1))
    v = man["bands"][band]["visits"]
    moved = c.get("x0") is not None and c.get("shift_arcsec", 0) and c.get("matches_prediction", True) \
        and (c.get("kind") in ("mover", "known target"))
    if moved and len(v) >= 2:
        ra0, dec0 = wgrid.wcs_pix2world([[c["x0"], c["y0"]]], 0)[0]
        out.update(ra0=float(ra0), dec0=float(dec0), mjd0=v[0]["mjd"], ra1=float(ra1), dec1=float(dec1),
                   mjd1=v[-1]["mjd"])
    return out, c
