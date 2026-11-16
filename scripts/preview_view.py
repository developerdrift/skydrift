# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Render a built view (cache/views/... or docs/data/<key>/) to a PNG strip or a GIF.

Usage: python scripts/preview_view.py VIEW_DIR BAND OUT.(png|gif) [--mode visits|exp] [--max 8]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import render  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("view")
ap.add_argument("band")
ap.add_argument("out")
ap.add_argument("--mode", default="visits", choices=["visits", "exp"])
ap.add_argument("--max", type=int, default=8)
ap.add_argument("--scale", type=int, default=3)
a = ap.parse_args()
d = Path(a.view)
m = json.loads((d / "manifest.json").read_text())
h, w = m["shape"]
bd = m["bands"][a.band]
if a.mode == "visits":
    cube = np.fromfile(d / f"{a.band}_visits.f32", "<f4").reshape(-1, h, w)
    meta = bd["visits"]
    labels = [f"{a.band} {x['time'][:10]} +{x['days']:.0f}d n={x['n']} "
              f"{x['wav'][0]:.2f}-{x['wav'][1]:.2f}um" if x["wav"] else x["time"][:10] for x in meta]
else:
    enc = bd.get("enc", {}).get("exp")
    if enc:
        q = np.fromfile(d / f"{a.band}_exp.i16", "<i2").reshape(-1, h, w)
        cube = np.array([np.where(q[k] == -32768, np.nan, enc["offset"][k] + (q[k] + 32500.0) * enc["scale"][k])
                         for k in range(len(q))])
    else:
        cube = np.fromfile(d / f"{a.band}_exp.f32", "<f4").reshape(-1, h, w)
    meta = bd["exposures"]
    labels = [f"{a.band} {x['time']} {x['wav']:.3f}um" if x["wav"] else x["time"] for x in meta]
cube, labels = cube[:a.max], labels[:a.max]
st = bd["stretch"]["visits" if a.mode == "visits" else "exp"]
if a.out.endswith(".gif"):
    render.write_gif(list(cube), labels, a.out, st, scale=a.scale, duration_ms=700)
else:
    ims = [render.frame_image(f, st, lab, scale=a.scale) for f, lab in zip(cube, labels)]
    out = Image.new("RGB", (sum(i.width for i in ims) + 4 * (len(ims) - 1), ims[0].height), (40, 40, 40))
    x = 0
    for i in ims:
        out.paste(i, (x, 0))
        x += i.width + 4
    out.save(a.out)
print(a.out, len(cube), "frames")
