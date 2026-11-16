# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Write the static showcase into docs/ (GitHub Pages): same frontend, pre-built preset data.

Usage: .venv/Scripts/python export_showcase.py
Builds (or reuses) the view for each preset, then copies it to docs/data/<key>/.
Per-exposure cubes are stored as int16 with a per-frame linear scale to keep the site small
(the step is ~1/65000 of each frame's range); visit and all-epoch stacks stay float32.
"""
import json
import shutil
import sys
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
import astropy  # noqa: E402,F401  (import before touching its logger)
import logging  # noqa: E402
logging.getLogger("astropy").setLevel(logging.ERROR)
from app.server import CACHE, STATIC, presets  # noqa: E402
from engine import fetch, views  # noqa: E402

DOCS = ROOT / "docs"


def to_i16(src, dst, shape):
    a = np.fromfile(src, "<f4").reshape(-1, *shape)
    off, sc = [], []
    out = np.empty(a.shape, "<i2")
    for k, f in enumerate(a):
        ok = np.isfinite(f)
        lo, hi = (float(f[ok].min()), float(f[ok].max())) if ok.any() else (0.0, 1.0)
        s = (hi - lo) / 65000.0 or 1.0
        q = np.round((np.where(ok, f, lo) - lo) / s) - 32500
        out[k] = np.where(ok, q, -32768).astype("<i2")
        off.append(lo)
        sc.append(s)
    out.tofile(dst)
    return dict(type="i16", offset=off, scale=sc)


def main():
    data = DOCS / "data"
    if DOCS.exists():
        shutil.rmtree(DOCS / "static", ignore_errors=True)
        shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True, exist_ok=True)
    shutil.copytree(STATIC, DOCS / "static")
    shutil.copy(STATIC / "index.html", DOCS / "index.html")
    shutil.copy(STATIC / "validation.html", DOCS / "validation.html")
    shutil.copy(ROOT / "README.md", DOCS / "README.md")   # linked from the static-mode note
    (DOCS / ".nojekyll").write_text("")
    ps = presets()
    done = []
    for p in ps:
        print(f"{p['key']}: building/reusing view ...", flush=True)
        try:
            man = views.ensure_fresh(p["ra"], p["dec"], p["fov"], CACHE)
        except Exception as e:  # noqa: BLE001
            print(f"  FAILED: {type(e).__name__}: {e}")
            continue
        src = views.view_dir(CACHE, p["ra"], p["dec"], p["fov"])
        dst = data / p["key"]
        dst.mkdir()
        for b, bd in man["bands"].items():
            shutil.copy(src / f"{b}_visits.f32", dst / f"{b}_visits.f32")
            shutil.copy(src / f"{b}_all.f32", dst / f"{b}_all.f32")
            bd["enc"] = dict(exp=to_i16(src / f"{b}_exp.f32", dst / f"{b}_exp.i16", man["shape"]))
        (dst / "manifest.json").write_text(json.dumps(man))
        mb = sum(f.stat().st_size for f in dst.iterdir()) / 1e6
        print(f"  {len(man['bands'])} bands, {mb:.1f} MB", flush=True)
        done.append(p)
    (data / "presets.json").write_text(json.dumps(dict(mode="static", presets=done), indent=1))
    total = sum(f.stat().st_size for f in DOCS.rglob("*") if f.is_file()) / 1e6
    print(f"docs/ written: {len(done)}/{len(ps)} presets, {total:.1f} MB")


if __name__ == "__main__":
    main()
