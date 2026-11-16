# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Comparison stars for the truth check (Phase 3C).

LITERATURE VALUES QUOTED FROM MEMORY - NOT live Gaia DR3 queries. IRSA TAP (Gaia DR3) and
SIMBAD were unreachable when this was written (2026-11-15). Positions are J2000 at epoch
J2000.0; pmra includes cos(dec); all in arcsec(/yr). Any star whose measured motion disagrees
with these values is reported, not dropped, so a wrong value here shows up as an outlier.
Replace with gaia_dr3_source values when TAP is back.
"""
from astropy.coordinates import SkyCoord
import astropy.units as u

# name, RA (hms), Dec (dms), pmra, pmdec ("/yr), parallax (")
STARS = [
    ("Van Maanen 2", "00 49 09.90", "+05 23 19.0", 1.232, -2.709, 0.2323),
    ("Teegarden's Star", "02 53 00.85", "+16 52 52.6", 3.430, -3.805, 0.2615),
    ("Kapteyn's Star", "05 11 40.59", "-45 01 06.4", 6.506, -5.731, 0.2548),
    ("Luyten's Star", "07 27 24.50", "+05 13 32.8", 0.571, -3.694, 0.2627),
    ("Wolf 359", "10 56 28.86", "+07 00 52.8", -3.842, -2.725, 0.4153),
    ("Lalande 21185", "11 03 20.19", "+35 58 11.6", -0.580, -4.767, 0.3925),
    ("Ross 128", "11 47 44.40", "+00 48 16.4", 0.607, -1.223, 0.2963),
    ("Groombridge 1830", "11 52 58.77", "+37 43 07.2", 4.003, -5.813, 0.1095),
    ("Proxima Centauri", "14 29 42.95", "-62 40 46.2", -3.781, 0.770, 0.7685),
    ("Lacaille 9352", "23 05 52.04", "-35 51 11.1", 6.768, 1.327, 0.3037),
    ("Gliese 1", "00 05 24.43", "-37 21 26.7", 5.634, -2.338, 0.2302),
    ("YZ Ceti", "01 12 30.64", "-16 59 56.4", 1.205, 0.638, 0.2712),
    ("Ross 248", "23 41 54.99", "+44 10 30.3", 0.111, -1.592, 0.3162),
    ("Wolf 1061", "16 30 18.06", "-12 39 45.3", -0.094, -1.183, 0.2321),
    ("Gliese 687", "17 36 25.90", "+68 20 20.9", -0.320, -1.270, 0.2205),
    ("Gliese 412 A", "11 05 28.58", "+43 31 36.4", -4.406, 0.943, 0.2039),
    ("Ross 154", "18 49 49.36", "-23 50 10.4", 0.638, -0.191, 0.3365),
    ("61 Cygni A", "21 06 53.94", "+38 44 57.9", 4.164, 3.250, 0.2862),
    ("Gliese 15 A", "00 18 22.89", "+44 01 22.6", 2.891, 0.411, 0.2804),
    ("Gliese 445", "11 47 41.38", "+78 41 28.2", 0.744, 0.480, 0.1902),
    ("Kruger 60 A", "22 27 59.47", "+57 41 45.1", -0.725, -0.223, 0.2490),
    ("Gliese 83.1", "02 00 12.96", "+13 03 07.0", 1.096, -1.772, 0.2236),
    ("Gliese 1061", "03 35 59.70", "-44 30 45.3", 0.745, -0.374, 0.2722),
    ("Gliese 876", "22 53 16.73", "-14 15 49.3", 0.960, -0.676, 0.2147),
    ("Gliese 725 A", "18 42 46.70", "+59 37 49.4", -1.311, 1.792, 0.2840),
    ("Gliese 380", "10 11 22.14", "+49 27 15.3", -1.361, -0.506, 0.2054),
    ("Epsilon Indi A", "22 03 21.66", "-56 47 09.5", 3.966, -2.537, 0.2741),
    ("Gliese 674", "17 28 39.95", "-46 53 42.7", 0.573, -0.880, 0.2203),
    ("Gliese 440 (WD)", "11 45 42.92", "-64 50 29.5", 2.661, -0.344, 0.2161),
    ("Gliese 293 (WD)", "07 53 08.18", "-67 47 31.5", 1.090, -1.997, 0.1260),
]

# Fainter objects (late M, L, T dwarfs), less likely to saturate. Positions at the epoch given
# (WISE/2MASS designations are at their survey epochs). Same caveat: from memory, unverified.
FAINT = [
    # name, RA, Dec, epoch, pmra, pmdec, parallax
    ("Luhman 16AB", "10 49 15.57", "-53 19 06.1", 2010.5, -2.762, 0.358, 0.5010),
    ("VB 10", "19 16 57.62", "+05 09 02.2", 2000.0, -0.578, -1.331, 0.1685),
    ("UGPS J0722-0540", "07 22 27.29", "-05 40 30.0", 2010.0, -0.904, 0.352, 0.2420),
    ("2MASS J0415-0935", "04 15 19.54", "-09 35 06.6", 1998.8, 2.214, 0.536, 0.1752),
    ("WISE J1741+2553", "17 41 24.22", "+25 53 19.5", 2010.5, -0.498, -1.469, 0.2140),
    ("LP 944-20", "03 39 35.22", "-35 25 44.1", 2000.0, 0.326, 0.296, 0.1563),
]


def stars():
    out = []
    rows = [(n, r, d, 2000.0, a, b, p) for n, r, d, a, b, p in STARS] + list(FAINT)
    for name, ra, dec, ep, pmra, pmdec, plx in rows:
        c = SkyCoord(ra, dec, unit=(u.hourangle, u.deg))
        out.append(dict(name=name, ra=c.ra.deg, dec=c.dec.deg, epoch=ep, pmra=pmra, pmdec=pmdec,
                        plx=plx, note="literature value from memory, not a live Gaia DR3 query"))
    return out
