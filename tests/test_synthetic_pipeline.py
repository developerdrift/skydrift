# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""End-to-end pipeline logic on SYNTHETIC cutouts (tests/synthetic.py).

This checks that the code does what it should with a known input. It proves nothing
about real SPHEREx data or about any real target.
"""
import numpy as np
import pytest
from astropy.time import Time

from engine import calibrate, measure, pipeline, stack
from tests import synthetic


@pytest.fixture(scope="module")
def field(tmp_path_factory):
    d = tmp_path_factory.mktemp("syn")
    return synthetic.make_field(d)


def test_spectral_wcs_tab_lookup(field):
    records, truth = field
    r = records[4]
    wav, bw = calibrate.wavelength_at(r["path"], truth["mover"]["ra"], truth["mover"]["dec"])
    # Cutout centre: wav0 + 0.004 * (y - n/2) with y = 19.5 (0-based centre), n = 40.
    assert wav == pytest.approx(r["wav0"] - 0.002, abs=0.003)
    assert bw == pytest.approx(wav / 40.0, rel=0.02)


def test_calibrate_masks_hot_and_removes_background(field):
    records, _ = field
    c = calibrate.load(records[0]["path"])
    assert calibrate.DEFAULT_MASK & (1 << synthetic.HOT_BIT)
    assert not calibrate.DEFAULT_MASK & (1 << 21)          # SOURCE stays unmasked
    sci, var, info = calibrate.calibrate(c)
    hot = (c.flags & (1 << synthetic.HOT_BIT)) != 0
    src_only = c.flags == (1 << 21)
    assert np.isnan(sci[hot]).all() and np.isfinite(sci[src_only]).all()
    assert set(info["flag_bits_present"]) == {"HOT", "SOURCE"}
    assert abs(np.nanmedian(sci)) < 0.3          # ZODI + offset removed
    assert np.nanmax(sci) < 1e3                  # hot pixels gone


def test_ivw_weights():
    a, b = np.full((2, 2), 1.0), np.full((2, 2), 4.0)
    img, var, n = stack.ivw([a, b], [np.full((2, 2), 1.0), np.full((2, 2), 3.0)])
    assert img[0, 0] == pytest.approx((1 * 1 + 4 / 3) / (1 + 1 / 3))
    assert var[0, 0] == pytest.approx(1 / (1 + 1 / 3))


def test_mover_shifts_static_stars_stay(field, tmp_path):
    records, truth = field
    mv = truth["mover"]
    frames, w = pipeline.build_frames(records, mv["ra"], mv["dec"], fov_arcmin=3.0)
    assert len(frames) == len(records)
    res = pipeline.visit_blink(frames, "D6", tmp_path / "SYNTHETIC_blink.gif")
    stacks = res["stacks"]
    assert len(stacks) == 4 and (tmp_path / "SYNTHETIC_blink.gif").exists()

    def expected_px(star, mjd):
        ra, dec = synthetic.star_position(star, mjd, truth["mjd_ref"])
        return w.wcs_world2pix([[ra, dec]], 0)[0]

    mover_err, static_err = [], []
    for s in stacks:
        ex, ey = expected_px(mv, s["mjd_mean"])
        mx, my = measure.centroid(s["img"], ex, ey, r=3)
        mover_err.append(np.hypot(mx - ex, my - ey))
        for st in truth["stars"]:
            sx, sy = expected_px(st, s["mjd_mean"])
            if 6 < sx < s["img"].shape[1] - 6 and 6 < sy < s["img"].shape[0] - 6:
                cx, cy = measure.centroid(s["img"], sx, sy, r=3)
                if np.isfinite(cx):
                    static_err.append(np.hypot(cx - sx, cy - sy))
    # Mover travels 10"/yr * 1.48 yr = 14.8" = ~4.8 px on the 3.1"/px grid.
    first = measure.centroid(stacks[0]["img"], *expected_px(mv, stacks[0]["mjd_mean"]), r=3)
    last = measure.centroid(stacks[-1]["img"], *expected_px(mv, stacks[-1]["mjd_mean"]), r=3)
    shift_arcsec = np.hypot(last[0] - first[0], last[1] - first[1]) * 3.1
    assert shift_arcsec == pytest.approx(10.0 * 540 / 365.25, abs=2.0)
    assert np.median(mover_err) < 0.7
    assert np.median(static_err) < 0.7
