# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Background prefetch: find exposures and cache cutouts for all five test targets.

Usage: python scripts/prefetch.py [--fov 6]   (log lines go to stdout)
Cutouts are cached under cache/<ra>_<dec>_<size>/<release>/ keyed on the grid centre at 2025.9.
"""
import argparse
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
import astropy  # noqa: E402,F401  (import before touching its logger)
import logging  # noqa: E402
logging.getLogger("astropy").setLevel(logging.ERROR)
from astropy.time import Time  # noqa: E402
from engine import fetch  # noqa: E402
from engine.targets import TARGETS, position_at  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--fov", type=float, default=6.0)
a = ap.parse_args()
size = round(a.fov / 60 * 1.15, 4)
mjd_mid = Time(2025.9, format="jyear").mjd
print(time.strftime("%H:%M:%S"), "TAP available:", fetch.tap_available(), flush=True)
for key, tg in TARGETS.items():
    t0 = time.time()
    ra, dec = position_at(key, mjd_mid)
    try:
        t = fetch.find_exposures(ra, dec, size, ROOT / "cache", log=lambda m: print(m, flush=True))
        paths = fetch.fetch_cutouts(t, ra, dec, size, ROOT / "cache")
        ok = sum(p is not None for p in paths)
        bands = {}
        for r in t:
            bands[str(r["band"])] = bands.get(str(r["band"]), 0) + 1
        print(f"{time.strftime('%H:%M:%S')} {key}: {len(t)} exposures, {ok} cutouts cached, "
              f"visits={len(set(t['visit'])) if len(t) else 0}, per band={dict(sorted(bands.items()))}, "
              f"{(time.time() - t0) / 60:.1f} min [{t.meta.get('source')}]", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"{time.strftime('%H:%M:%S')} {key}: FAILED {type(e).__name__}: {e}", flush=True)
print(time.strftime("%H:%M:%S"), "prefetch done", flush=True)
