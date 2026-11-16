# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Candidate finder on SYNTHETIC data: the injected mover must be found, static stars not."""
import numpy as np

from engine import candidates, pipeline, stack
from tests import synthetic


def test_finds_injected_mover(tmp_path):
    (tmp_path / "f").mkdir()
    recs, truth = synthetic.make_field(tmp_path / "f", per_visit=4, mover_pm=(-12.0, 3.0))
    mv = truth["mover"]
    frames, w = pipeline.build_frames(recs, mv["ra"], mv["dec"], fov_arcmin=3.0)
    st = stack.group_stacks(frames)
    cands, summ = candidates.find(st, w, 3.1)
    movers = [c for c in cands if c["kind"] == "mover"]
    assert movers, (cands, summ)
    top = movers[0]
    exp_shift = np.hypot(12.0, 3.0) * summ["baseline_days"] / 365.25
    assert abs(top["shift_arcsec"] - exp_shift) < 2.0
    assert abs(top["ra"] - mv["ra"]) * 3600 < 30
    # pmra < 0 means moving west: position angle should be roughly 284 deg (W, slightly N)
    assert 250 < top["pa_deg"] < 310
    assert len(movers) == 1, movers
