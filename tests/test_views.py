# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""build_view end to end on SYNTHETIC cutouts (logic only, no network)."""
import json

import numpy as np
from astropy.table import Table

from engine import fetch, views
from tests import synthetic


def test_build_view_synthetic(tmp_path, monkeypatch):
    (tmp_path / "fits").mkdir()
    recs, truth = synthetic.make_field(tmp_path / "fits")
    ra, dec, fov = truth["mover"]["ra"], truth["mover"]["dec"], 3.0
    t = Table(dict(planeid=[r["planeid"] for r in recs], obsid=[r["obsid"] for r in recs],
                   band=[r["band"] for r in recs], mjd=[r["mjd"] for r in recs],
                   visit=fetch.cluster_visits([r["mjd"] for r in recs]),
                   release=["SYN"] * len(recs), uri=["x"] * len(recs)))
    t.meta["source"] = "synthetic"
    monkeypatch.setattr(fetch, "find_exposures", lambda *a, **k: t)
    monkeypatch.setattr(fetch, "fetch_cutouts", lambda *a, **k: [r["path"] for r in recs])
    man = views.build_view(ra, dec, fov, tmp_path / "cache")
    d = views.view_dir(tmp_path / "cache", ra, dec, fov)
    assert json.loads((d / "manifest.json").read_text())["n_found"] == len(recs)
    b = man["bands"]["D6"]
    assert len(b["visits"]) == 4 and len(b["exposures"]) == 12
    h, w = man["shape"]
    assert np.fromfile(d / "D6_visits.f32", "<f4").size == 4 * h * w
    assert np.fromfile(d / "D6_exp.f32", "<f4").size == 12 * h * w
    assert b["visits"][1]["days"] > 100 and b["exposures"][0]["wav"] is not None
    assert {"lo", "hi", "soft"} <= set(b["stretch"]["visits"])
    # cached: second call returns without rebuilding
    assert views.build_view(ra, dec, fov, tmp_path / "cache")["built"] == man["built"]
