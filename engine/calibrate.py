# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Read a SPHEREx cutout, subtract ZODI, mask flagged pixels, remove residual background.

Cutout layout (verified on real DR1 files): PRIMARY (VERSION), IMAGE (MJy/sr), FLAGS,
VARIANCE, ZODI, EPSF, WCS-WAVE.

FLAGS bit meanings: the FITS headers carry no bit names, so they come from the
SPHEREx Explanatory Supplement (IRSA, SSDC-DP-017 v2.0, 2026-08-25, Sect. 3.2.5, pp. 31-33).
Masking choice: we exclude only the "clearly bad" bits, i.e. the document's own list of
"Flags for masking pixels for photometry calculations" (p. 43). Informational bits stay
unmasked. In particular SOURCE (bit 21, "pixel mapped to a known source") covers ~44% of
pixels and sits on every real star, so masking it would erase the very objects we blink.
Masking "any nonzero flag" was tried in Phase 0 and masked the target in every exposure.
"""
import warnings
from dataclasses import dataclass, field

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.wcs import WCS, FITSFixedWarning
import astropy.units as u

warnings.filterwarnings("ignore", category=FITSFixedWarning)

# Explanatory Supplement v2.0, Table in Sect. 3.2.5 (bit -> symbolic name).
FLAG_BITS = {0: "TRANSIENT", 1: "OVERFLOW", 2: "SUR_ERROR", 6: "NONFUNC", 7: "DICHROIC",
             9: "MISSING_DATA", 10: "HOT", 11: "COLD", 12: "FULLSAMPLE", 14: "PHANMISS",
             15: "NONLINEAR", 17: "PERSIST", 19: "OUTLIER", 20: "CROSSTALK", 21: "SOURCE",
             22: "GHOST", 23: "GHOST_FPA", 24: "GHOST_EXT", 25: "STREAK", 26: "BLOOM",
             27: "SNOWBALL", 28: "HALO", 29: "SATELLITE_HALO"}
# Same document, p. 43: "Flags for masking pixels for photometry calculations".
PHOTOMETRY_MASK_NAMES = ("SUR_ERROR", "NONFUNC", "MISSING_DATA", "HOT", "COLD", "NONLINEAR",
                         "PERSIST", "BLOOM", "SNOWBALL", "HALO", "SATELLITE_HALO")
DEFAULT_MASK = sum(1 << b for b, n in FLAG_BITS.items() if n in PHOTOMETRY_MASK_NAMES)


@dataclass
class Cutout:
    path: str
    image: np.ndarray
    flags: np.ndarray
    variance: np.ndarray
    zodi: np.ndarray
    wcs: WCS
    header: fits.Header
    version: str | None
    bunit: str | None
    flag_names: dict = field(default_factory=dict)


def flag_bit_names(hdr):
    out = {}
    for k, v in hdr.items():
        name = k.replace("HIERARCH ", "")
        if name.startswith("MP_"):
            try:
                out[int(v)] = name
            except (TypeError, ValueError):
                pass
    return out


def bit_name(b, flag_names=None):
    return (flag_names or {}).get(b) or FLAG_BITS.get(b, f"bit{b}")


def load(path):
    with fits.open(path) as hl:
        h = hl["IMAGE"].header
        return Cutout(
            path=str(path),
            image=hl["IMAGE"].data.astype(np.float64),
            flags=hl["FLAGS"].data.astype(np.int64),
            variance=hl["VARIANCE"].data.astype(np.float64),
            zodi=hl["ZODI"].data.astype(np.float64),
            wcs=WCS(h),
            header=h.copy(),
            version=hl[0].header.get("VERSION"),
            bunit=h.get("BUNIT"),
            flag_names=flag_bit_names(hl["FLAGS"].header),
        )


def wavelength_at(path, ra, dec):
    """(wavelength_um, bandwidth_um) at a sky position, from the spectral WCS (key W).

    Follows the IRSA recipe in SPEC.md. Returns (nan, nan) if the spectral WCS can't be read.
    """
    from astropy.coordinates import SkyCoord
    try:
        with fits.open(path) as hl:
            h = hl["IMAGE"].header
            x, y = WCS(h).world_to_pixel(SkyCoord(ra * u.deg, dec * u.deg))
            sw = WCS(h, fobj=hl, key="W")
            sw.sip = None
            vals = sw.pixel_to_world_values(x, y)
            units = [u.Unit(str(cu)) if str(cu) else u.um for cu in sw.wcs.cunit]
            wav = (float(vals[0]) * units[0]).to(u.um).value
            bw = (float(vals[1]) * units[1]).to(u.um).value if len(vals) > 1 else np.nan
            return wav, bw
    except Exception:  # noqa: BLE001
        return np.nan, np.nan


def calibrate(c: Cutout, mask_bits=None):
    """Return (sci, var, info). Masked pixels are NaN in both arrays.

    sci = IMAGE - ZODI, flagged pixels masked, then the sigma-clipped median removed.
    """
    if mask_bits is None:
        mask_bits = DEFAULT_MASK
    sci = c.image - c.zodi
    flagged_any = c.flags != 0
    bad = (c.flags & mask_bits) != 0
    bad |= ~np.isfinite(sci) | ~np.isfinite(c.variance) | (c.variance <= 0)
    sci = np.where(bad, np.nan, sci)
    var = np.where(bad, np.nan, c.variance)
    good = np.isfinite(sci)
    bkg = 0.0
    if good.sum() > 10:
        _, bkg, _ = sigma_clipped_stats(sci[good], sigma=3.0, maxiters=5)
        sci = sci - bkg
    present = sorted({b for b in range(63) if np.any(c.flags & (1 << b))})
    info = dict(
        flag_frac_any=float(flagged_any.mean()),
        flag_frac_masked=float(bad.mean()),
        flag_bits_present=[bit_name(b, c.flag_names) for b in present],
        residual_bkg=float(bkg),
        version=c.version,
        bunit=c.bunit,
    )
    return sci, var, info
