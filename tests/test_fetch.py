# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Offline unit tests: visit clustering, URL building, dedupe, cache reuse."""
import numpy as np
from astropy.table import Table

from engine import fetch


def test_cluster_visits_gap():
    mjd = [60000, 60001, 60002.5, 60200, 60201, 60400]
    assert list(fetch.cluster_visits(mjd)) == [0, 0, 0, 1, 1, 2]


def test_cluster_visits_unsorted_and_boundary():
    mjd = [60100, 60000, 60030, 60060.5]  # 30.0 is not > 30, 30.5 is
    assert list(fetch.cluster_visits(mjd)) == [2, 0, 0, 1]
    assert fetch.cluster_visits([]).size == 0


def test_cutout_url():
    u = fetch.cutout_url("/ibe/data/spherex/x.fits", 133.76, -7.243, 0.05)
    assert u == "https://irsa.ipac.caltech.edu/ibe/data/spherex/x.fits?center=133.760000,-7.243000d&size=0.05"


def test_build_query_has_required_clauses():
    q = fetch.build_query(10.0, -5.0, ["D6"])
    assert "CONTAINS(POINT('ICRS', 10.0000000, -5.0000000), p.poly)" in q
    assert "'SPHEREx-D6'" in q and "ORDER BY p.time_bounds_lower" in q


def test_dedupe_prefers_dr1():
    t = Table(dict(obsid=["a", "a", "b"], energy_bandpassname=["SPHEREx-D6"] * 3,
                   datarelease=["QR3", "DR1", "QR3"], metarelease=["", "", ""],
                   time_bounds_lower=[1.0, 1.0, 2.0]))
    d = fetch.dedupe(t)
    assert len(d) == 2 and list(d["datarelease"]) == ["DR1", "QR3"]


def test_fetch_cutouts_uses_cache(tmp_path):
    t = Table(dict(planeid=["p1", "p2"], uri=["u1", "u2"], release=["R", "R"]))
    calls = []

    def fake(url, dest):
        calls.append(url)
        dest.write_bytes(b"x")
        return dest

    p1 = fetch.fetch_cutouts(t, 1.0, 2.0, 0.05, tmp_path, downloader=fake)
    p2 = fetch.fetch_cutouts(t, 1.0, 2.0, 0.05, tmp_path, downloader=fake)
    assert all(p is not None for p in p1) and p1 == p2
    assert len(calls) == 2  # second run fully cached
