# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
import pytest

from engine.coords import CoordError, parse_dec, parse_fov, parse_ra


def test_decimal():
    assert parse_ra("269.452") == pytest.approx(269.452)
    assert parse_dec("-7.245") == pytest.approx(-7.245)
    assert parse_ra("10d") == pytest.approx(10.0)


def test_sexagesimal_forms():
    assert parse_ra("17h57m48.5s") == pytest.approx(269.452083, abs=1e-5)
    assert parse_ra("17:57:48.5") == pytest.approx(269.452083, abs=1e-5)
    assert parse_ra("17 57 48.5") == pytest.approx(269.452083, abs=1e-5)
    assert parse_dec("+04d41m36s") == pytest.approx(4.693333, abs=1e-5)
    assert parse_dec("-07:14:42.53") == pytest.approx(-7.245147, abs=1e-5)
    assert parse_dec("−56 47 10") == pytest.approx(-56.786111, abs=1e-5)


def test_errors():
    for bad in ["", "abc", "400", "-1"]:
        with pytest.raises(CoordError):
            parse_ra(bad)
    with pytest.raises(CoordError):
        parse_dec("95")
    with pytest.raises(CoordError):
        parse_fov("45")
    assert parse_fov("6") == 6.0
