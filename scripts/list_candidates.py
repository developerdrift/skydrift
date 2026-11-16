# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Build (or reuse) preset views and print their candidate lists. Usage: python scripts/list_candidates.py"""
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")
import astropy  # noqa: E402,F401
import logging  # noqa: E402
logging.getLogger("astropy").setLevel(logging.ERROR)
from engine import fetch, views  # noqa: E402
from engine.targets import preset_positions  # noqa: E402

fetch._TAP_OK = None
for p in preset_positions():
    m = views.build_view(p["ra"], p["dec"], p["fov"], "cache")
    for b, bd in m["bands"].items():
        sm, cs = bd["cand_summary"], bd["candidates"]
        if not cs and "n_matched" not in sm:
            continue
        print(f"{p['key']} {b}: matched {sm.get('n_matched')} baseline {sm.get('baseline_days')} d, "
              f"field scatter {sm.get('field_scatter_arcsec')}\", wav overlap {sm.get('wav_overlap')} "
              f"{sm.get('note') or ''}")
        for c in cs:
            print(f"   [{c['kind']}] score {c.get('score')} snr {c.get('snr')} shift {c.get('shift_arcsec')}\" "
                  f"dipole {c.get('dipole_confirmed')} :: {c['label']}")
