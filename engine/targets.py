# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""The five test targets with reference positions and proper motions.

UNVERIFIED: written while IRSA TAP (Gaia DR3) and SIMBAD were unreachable (2026-11-15).
Values are literature numbers quoted from memory. Re-derive from gaia_dr3_source when TAP
is back. Proper motions are in arcsec/yr (pmra includes cos(dec)). Parallax is ignored.
"""
import numpy as np
from astropy.time import Time

TARGETS = {
    "barnard": dict(name="Barnard's Star", ra=269.452075, dec=4.693391, epoch=2000.0,
                    pmra=-0.8016, pmdec=10.3624, note="J2000 position; Gaia DR3 PM (from memory)"),
    "eps_indi_b": dict(name="Epsilon Indi Ba/Bb", ra=331.04383, dec=-56.78272, epoch=2000.0,
                       pmra=3.966, pmdec=-2.537, note="J2000 (22h04m10.52s -56d46m57.8s); system PM"),
    "wise0855": dict(name="WISE 0855-0714", ra=133.795129, dec=-7.245147, epoch=2010.5,
                     pmra=-8.118, pmdec=0.680,
                     note="challenge coords; epoch 2010.5 favoured by the Phase 0 D6 diagnostic "
                          "(provisional); PM Luhman & Esplin 2016"),
    "rw_aur": dict(name="RW Aurigae", ra=76.956417, dec=30.401417, epoch=2000.0,
                   pmra=0.0, pmdec=-0.025, note="young variable; PM small (approx.)"),
    "r_dra": dict(name="R Draconis", ra=248.16750, dec=66.75500, epoch=2000.0,
                  pmra=0.0, pmdec=0.0, note="Mira variable; PM negligible at this scale"),
}


def position_at(key_or_target, mjd):
    t = TARGETS[key_or_target] if isinstance(key_or_target, str) else key_or_target
    dt = (mjd - Time(t["epoch"], format="jyear").mjd) / 365.25
    dec = t["dec"] + t["pmdec"] * dt / 3600.0
    ra = t["ra"] + t["pmra"] * dt / 3600.0 / np.cos(np.radians(dec))
    return float(ra), float(dec)


PRESET_EPOCH_JYEAR = 2025.9
PRESET_FOV = 6.0
PRESET_BAND = {"wise0855": "D6"}


def preset_positions():
    """Preset grid centres (position at 2025.9, rounded to 1e-5 deg). The app, the exporter
    and the coverage daemon all use exactly these, so they share one cache."""
    mjd = Time(PRESET_EPOCH_JYEAR, format="jyear").mjd
    out = []
    for key, t in TARGETS.items():
        ra, dec = position_at(key, mjd)
        out.append(dict(key=key, name=t["name"], ra=round(ra, 5), dec=round(dec, 5),
                        fov=PRESET_FOV, band=PRESET_BAND.get(key, "D1"), note=t["note"]))
    return out
