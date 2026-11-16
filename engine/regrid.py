# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Reproject calibrated cutouts onto a common north-up grid centred on the target.

Named regrid.py (not reproject.py) so it never shadows the `reproject` package.
Default output scale is half the nominal native pixel (2x oversampling).
UNVERIFIED: native scale 6.2"/px is the SPEC.md expectation, not yet measured.
"""
import numpy as np
from astropy.wcs import WCS
from reproject import reproject_interp

NATIVE_ARCSEC = 6.2


def target_wcs(ra, dec, fov_arcmin, scale_arcsec=NATIVE_ARCSEC / 2):
    n = int(np.ceil(fov_arcmin * 60.0 / scale_arcsec))
    n += (n + 1) % 2  # odd, so the target sits on the centre pixel
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.cunit = ["deg", "deg"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-scale_arcsec / 3600.0, scale_arcsec / 3600.0]
    return w, (n, n)


def regrid(sci, var, wcs_in, wcs_out, shape):
    """Bilinear reprojection of surface brightness and variance. NaN = no data."""
    s, fp = reproject_interp((sci, wcs_in), wcs_out, shape_out=shape, order="bilinear")
    v, _ = reproject_interp((var, wcs_in), wcs_out, shape_out=shape, order="bilinear")
    bad = (fp <= 0) | ~np.isfinite(s) | ~np.isfinite(v) | (v <= 0)
    s[bad] = np.nan
    v[bad] = np.nan
    return s, v
