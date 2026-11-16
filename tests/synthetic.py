# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""SYNTHETIC SPHEREx-like cutouts for testing pipeline logic ONLY.

These files are made up. They copy the HDU layout from SPEC.md (primary with VERSION,
IMAGE, FLAGS, VARIANCE, ZODI, EPSF, WCS-WAVE) so the code paths run, but none of their
values say anything about real SPHEREx data or any real target. VERSION is set to
"SYNTHETIC" so they can never be mistaken for real files.

The spectral WCS is an alternate -TAB WCS (key W) that looks up a WCS-WAVE binary table.
That is my best guess at the real layout, based on the SPEC.md recipe
WCS(header, fobj=hdulist, key="W"). It must be checked against a real cutout.
"""
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

HOT_BIT = 10   # HOT in the Explanatory Supplement table


def _spatial_wcs(ra0, dec0, n, scale_arcsec, rot_deg):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.cunit = ["deg", "deg"]
    w.wcs.crval = [ra0, dec0]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    s, th = scale_arcsec / 3600.0, np.radians(rot_deg)
    w.wcs.cd = [[-s * np.cos(th), s * np.sin(th)], [s * np.sin(th), s * np.cos(th)]]
    return w


def star_position(star, mjd, mjd_ref):
    dt = (mjd - mjd_ref) / 365.25
    dec = star["dec"] + star.get("pmdec", 0.0) * dt / 3600.0
    ra = star["ra"] + star.get("pmra", 0.0) * dt / 3600.0 / np.cos(np.radians(dec))
    return ra, dec


def make_cutout(path, ra0, dec0, mjd, wav0_um, stars, mjd_ref, n=40, scale_arcsec=6.2,
                rot_deg=12.0, psf_sigma_px=0.6, noise=0.5, seed=0, n_hot=3):
    rng = np.random.default_rng(seed)
    w = _spatial_wcs(ra0, dec0, n, scale_arcsec, rot_deg)
    yy, xx = np.mgrid[:n, :n].astype(float)
    wav = wav0_um + 0.004 * (yy - n / 2)        # wavelength varies along one detector axis
    bw = wav / 40.0
    sky = np.zeros((n, n))
    for st in stars:
        ra, dec = star_position(st, mjd, mjd_ref)
        x, y = w.wcs_world2pix([[ra, dec]], 0)[0]
        if not (-5 < x < n + 5 and -5 < y < n + 5):
            continue
        wl = wav0_um + 0.004 * (y - n / 2)
        flux = st["flux"] * (wl / 3.0) ** st.get("alpha", 0.0)
        sky += flux * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * psf_sigma_px ** 2)) / (
            2 * np.pi * psf_sigma_px ** 2)
    zodi = 30.0 + 0.15 * xx + 0.08 * yy
    var = noise ** 2 + 0.01 * np.clip(sky, 0, None)
    img = sky + zodi + rng.normal(0, 1, (n, n)) * np.sqrt(var)
    flags = np.zeros((n, n), np.int32)
    for _ in range(n_hot):
        i, j = rng.integers(2, n - 2, 2)
        img[i, j] = 1e4
        flags[i, j] |= 1 << HOT_BIT
    flags[(img - zodi) > 5 * noise] |= 1 << 21   # SOURCE (informational): must NOT be masked
    img -= 2.0  # a residual offset for the background step to remove

    prim = fits.PrimaryHDU()
    prim.header["VERSION"] = "SYNTHETIC"
    prim.header["COMMENT"] = "SYNTHETIC TEST DATA - not SPHEREx"
    h = w.to_header()
    h["BUNIT"] = "synthetic"
    h["MJD-OBS"] = mjd
    # Alternate spectral WCS (key W) using the -TAB lookup (FITS Paper III).
    h["WCSAXESW"] = 2
    h["CTYPE1W"], h["CTYPE2W"] = "WAVE-TAB", "BWID-TAB"
    h["CUNIT1W"], h["CUNIT2W"] = "um", "um"
    for i, idx in ((1, "X"), (2, "Y")):
        h[f"CRPIX{i}W"], h[f"CDELT{i}W"], h[f"CRVAL{i}W"] = 0.0, 1.0, 0.0
        h[f"PS{i}_0W"], h[f"PS{i}_1W"], h[f"PS{i}_2W"] = "WCS-WAVE", "COORDS", idx
        h[f"PV{i}_3W"] = i
    coords = np.stack([wav, bw], axis=-1)[None]          # (1, ny, nx, 2) -> TDIM (2,nx,ny)
    tab = fits.BinTableHDU.from_columns([
        fits.Column(name="COORDS", format=f"{2 * n * n}D", dim=f"(2,{n},{n})", array=coords),
        fits.Column(name="X", format=f"{n}D", array=(np.arange(n) + 1.0)[None]),
        fits.Column(name="Y", format=f"{n}D", array=(np.arange(n) + 1.0)[None]),
    ], name="WCS-WAVE")
    fh = fits.Header()   # real FLAGS headers carry no bit names
    hl = fits.HDUList([
        prim,
        fits.ImageHDU(img.astype(np.float32), h, name="IMAGE"),
        fits.ImageHDU(flags, fh, name="FLAGS"),
        fits.ImageHDU(var.astype(np.float32), name="VARIANCE"),
        fits.ImageHDU(zodi.astype(np.float32), name="ZODI"),
        fits.ImageHDU(np.zeros((5, 5), np.float32), name="EPSF"),
        tab,
    ])
    hl.writeto(path, overwrite=True)
    return path


def make_field(out_dir, ra0=150.0, dec0=10.0, n_visits=4, per_visit=3, seed=1,
               mover_pm=(-10.0, 0.0), band="D6"):
    """A field of static stars plus one mover at the centre. Returns (records, truth)."""
    rng = np.random.default_rng(seed)
    mjd_ref = 60800.0
    stars = []
    for _ in range(12):
        r = np.sqrt(rng.uniform(0.0, 1.0)) * 1.5 / 60
        th = rng.uniform(0, 2 * np.pi)
        stars.append(dict(ra=ra0 + r * np.cos(th) / np.cos(np.radians(dec0)),
                          dec=dec0 + r * np.sin(th), flux=rng.uniform(40, 200),
                          alpha=rng.uniform(-2, 2)))
    mover = dict(ra=ra0, dec=dec0, flux=150.0, alpha=1.0, pmra=mover_pm[0], pmdec=mover_pm[1])
    records = []
    k = 0
    for v in range(n_visits):
        for e in range(per_visit):
            mjd = mjd_ref + 180.0 * v + 0.5 * e
            wav0 = 4.4 + 0.15 * e + 0.03 * v       # each exposure sees a different wavelength
            p = out_dir / f"syn_{band}_{k:03d}.fits"
            make_cutout(p, ra0, dec0, mjd, wav0, stars + [mover], mjd_ref, seed=seed * 100 + k)
            records.append(dict(path=p, band=band, visit=v, mjd=mjd, planeid=f"SYN{k:03d}",
                                obsid=f"SYNOBS{k:03d}", release="SYNTHETIC", wav0=wav0))
            k += 1
    return records, dict(stars=stars, mover=mover, mjd_ref=mjd_ref)
