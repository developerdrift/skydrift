# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Parse user RA/Dec input: decimal degrees or sexagesimal (hms/dms, colons or spaces)."""
import re

from astropy.coordinates import Angle
import astropy.units as u


class CoordError(ValueError):
    pass


def _clean(s):
    return str(s).strip().replace("−", "-")


def parse_ra(s):
    s = _clean(s)
    if not s:
        raise CoordError("RA is empty")
    try:
        if re.fullmatch(r"[+-]?\d+(\.\d*)?([eE][+-]?\d+)?\s*(d|deg)?", s):
            v = float(re.sub(r"\s*(d|deg)$", "", s))
        else:
            v = Angle(s, unit=u.hourangle).deg if not re.search(r"[d°]", s) else Angle(s, unit=u.deg).deg
    except Exception as e:  # noqa: BLE001
        raise CoordError(f"Can't read RA '{s}'") from e
    if not 0 <= v < 360:
        raise CoordError(f"RA {v} is outside 0-360 deg")
    return float(v)


def parse_dec(s):
    s = _clean(s)
    if not s:
        raise CoordError("Dec is empty")
    try:
        if re.fullmatch(r"[+-]?\d+(\.\d*)?([eE][+-]?\d+)?\s*(d|deg)?", s):
            v = float(re.sub(r"\s*(d|deg)$", "", s))
        else:
            v = Angle(s, unit=u.deg).deg
    except Exception as e:  # noqa: BLE001
        raise CoordError(f"Can't read Dec '{s}'") from e
    if not -90 <= v <= 90:
        raise CoordError(f"Dec {v} is outside -90..90 deg")
    return float(v)


def parse_fov(s, lo=2.0, hi=30.0):
    try:
        v = float(s)
    except Exception as e:  # noqa: BLE001
        raise CoordError(f"Can't read field of view '{s}'") from e
    if not lo <= v <= hi:
        raise CoordError(f"Field of view must be {lo:g}-{hi:g} arcmin")
    return v
