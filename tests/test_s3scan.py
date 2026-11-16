# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Offline tests for the S3 fallback helpers."""
from engine import s3scan
from engine.calibrate import DEFAULT_MASK, FLAG_BITS


def test_release_order_prefers_dr_then_newest_qr():
    rels = ["qr2/", "dr1/", "qr3/"]
    assert sorted(rels, key=s3scan.release_order) == ["dr1/", "qr3/", "qr2/"]


def test_contains_square_and_ra_wrap():
    sq = [[359.0, -1.0], [1.0, -1.0], [1.0, 1.0], [359.0, 1.0]]
    assert s3scan.contains(sq, 0.0, 0.0)
    assert s3scan.contains(sq, 359.5, 0.5)
    assert not s3scan.contains(sq, 2.0, 0.0)


def test_name_regex():
    k = "dr1/level2/2025W18_1B/l2b-v27-2026-196/6/level2_2025W18_1B_0012_3D6_spx_l2b-v27-2026-196.fits"
    m = s3scan.NAME_RE.search(k)
    assert (m["period"], m["seq"], m["exp"], m["det"]) == ("2025W18_1B", "0012", "3", "6")


def test_default_mask_matches_supplement_list():
    names = {FLAG_BITS[b] for b in range(32) if DEFAULT_MASK & (1 << b)}
    assert names == {"SUR_ERROR", "NONFUNC", "MISSING_DATA", "HOT", "COLD", "NONLINEAR",
                     "PERSIST", "BLOOM", "SNOWBALL", "HALO", "SATELLITE_HALO"}
