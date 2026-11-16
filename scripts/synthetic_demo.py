# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Render a visit-blink GIF from SYNTHETIC cutouts (logic check only, not real data)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import pipeline  # noqa: E402
from tests import synthetic  # noqa: E402

out = Path(__file__).resolve().parents[1] / "synthetic_out"
(out / "fits").mkdir(parents=True, exist_ok=True)
records, truth = synthetic.make_field(out / "fits")
mv = truth["mover"]
frames, _ = pipeline.build_frames(records, mv["ra"], mv["dec"], fov_arcmin=3.0)
res = pipeline.visit_blink(frames, "D6", out / "SYNTHETIC_visit_blink_D6.gif", label_prefix="SYNTHETIC ")
print(len(frames), "frames ->", len(res["stacks"]), "visit stacks ->", out / "SYNTHETIC_visit_blink_D6.gif")
