# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""One full refresh, in dependency order, so derived results are never older than their data:
1. rebuild every preset view whose coverage grew (stacks + candidates are computed there),
2. re-run the truth check on the current cache,
3. export the static showcase into docs/,
4. regenerate demo/ assets from the same views.
Writes cache/refresh_status.json. Usage: python scripts/refresh.py
"""
import json
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
import astropy  # noqa: E402,F401
import logging  # noqa: E402
logging.getLogger("astropy").setLevel(logging.ERROR)
from engine import views  # noqa: E402
from engine.targets import preset_positions  # noqa: E402

CACHE = ROOT / "cache"


def refresh(log=print):
    t0 = time.time()
    status = dict(started=time.strftime("%Y-%m-%d %H:%M:%S"), presets={})
    for p in preset_positions():
        try:
            m = views.ensure_fresh(p["ra"], p["dec"], p["fov"], CACHE)
            status["presets"][p["key"]] = dict(
                exposures=m["n_found"], bands=len(m["bands"]),
                visits={b: len(bd["visits"]) for b, bd in m["bands"].items()},
                candidates=sum(len(bd.get("candidates", [])) for bd in m["bands"].values()), built=m["built"])
        except Exception as e:  # noqa: BLE001
            status["presets"][p["key"]] = dict(error=f"{type(e).__name__}: {e}"[:200])
        log(f"  view {p['key']}: {status['presets'][p['key']]}")
    try:
        import truth_check
        truth_check.main()
        tj = json.loads((ROOT / "app" / "static" / "validation" / "truth.json").read_text())
        status["truth"] = {k: tj[k] for k in ("n_measurements", "n_stars_measured", "n_consistent",
                                              "rms_vector_residual_arcsec", "rms_vector_residual_consistent_arcsec")}
    except Exception as e:  # noqa: BLE001
        status["truth"] = dict(error=f"{type(e).__name__}: {e}"[:200])
    log(f"  truth: {status['truth']}")
    try:
        import export_showcase
        export_showcase.main()
        status["export"] = "ok"
    except Exception as e:  # noqa: BLE001
        status["export"] = f"error: {type(e).__name__}: {e}"[:200]
    try:
        import make_demo
        make_demo.main()
        status["demo"] = "ok"
    except Exception as e:  # noqa: BLE001
        status["demo"] = f"error: {type(e).__name__}: {e}"[:200]
    status["seconds"] = round(time.time() - t0, 1)
    status["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (CACHE / "refresh_status.json").write_text(json.dumps(status, indent=1, default=str))
    return status


if __name__ == "__main__":
    refresh()
