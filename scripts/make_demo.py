# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Demo assets in demo/ from the CURRENT preset views (re-run any time to refresh):
  <key>_blink.gif / .mp4   visit blink of the detector with the most visits (labelled frames)
  wise0855_D1_vs_D6.png    all-epoch stacks: invisible at ~1 um, visible at ~4.6 um
All images are SPHEREx data rendered by SkyDrift; no generated imagery, no logos.
Usage: python scripts/make_demo.py
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import render, views  # noqa: E402
from engine.targets import preset_positions  # noqa: E402

OUT = ROOT / "demo"
OUT.mkdir(exist_ok=True)
CACHE = ROOT / "cache"
SIZE = 480


def load_cube(d, band, kind, shape):
    return np.fromfile(d / f"{band}_{kind}.f32", "<f4").reshape(-1, *shape)


def frame(img, st, label, title):
    im = render.frame_image(img, st, "", scale=1, crosshair=False).resize((SIZE, SIZE), Image.NEAREST)
    d = ImageDraw.Draw(im)
    c, g, L = SIZE / 2, 14, 40
    for x0, y0, x1, y1 in [(c - L, c, c - g, c), (c + g, c, c + L, c), (c, c - L, c, c - g), (c, c + g, c, c + L)]:
        d.line([x0, y0, x1, y1], fill=(255, 90, 90), width=2)
    d.rectangle([0, 0, SIZE, 34], fill=(0, 0, 0))
    d.text((8, 3), title, fill=(255, 255, 255))
    d.text((8, 18), label, fill=(190, 210, 255))
    d.rectangle([0, SIZE - 16, SIZE, SIZE], fill=(0, 0, 0))
    d.text((8, SIZE - 14), "SPHEREx data (NASA/IPAC IRSA) - SkyDrift. N up, E left.", fill=(170, 170, 170))
    return im


def main():
    import imageio.v2 as imageio
    made = []
    for p in preset_positions():
        d = views.view_dir(CACHE, p["ra"], p["dec"], p["fov"])
        if not (d / "manifest.json").exists():
            continue
        m = json.loads((d / "manifest.json").read_text())
        if not m["bands"]:
            continue
        band = max(m["bands"], key=lambda b: (len(m["bands"][b]["visits"]), b == p["band"]))
        bd = m["bands"][band]
        cube = load_cube(d, band, "visits", m["shape"])
        st = bd["stretch"]["visits"]
        ims = []
        for img, v in zip(cube, bd["visits"]):
            wl = f"{v['wav'][0]:.2f}-{v['wav'][1]:.2f} um" if v["wav"] else ""
            ims.append(frame(img, st, f"{band}  {v['time'][:10]}  +{v['days']:.0f} d  {wl}  ({v['n']} exp)", p["name"]))
        ims[0].save(OUT / f"{p['key']}_blink.gif", save_all=True, append_images=ims[1:], duration=700, loop=0)
        # ~4 s MP4: repeat the blink at 1.5 frames/s
        reps = max(1, int(6 / max(1, len(ims))))
        w = imageio.get_writer(OUT / f"{p['key']}_blink.mp4", fps=1.5, codec="libx264", quality=8,
                               macro_block_size=16)
        for _ in range(reps):
            for im in ims:
                w.append_data(np.asarray(im))
        w.close()
        made.append(f"{p['key']}: {band}, {len(ims)} visits")
    # WISE 0855: D1 vs D6 all-epoch stacks
    wp = [p for p in preset_positions() if p["key"] == "wise0855"][0]
    d = views.view_dir(CACHE, wp["ra"], wp["dec"], wp["fov"])
    if (d / "manifest.json").exists():
        m = json.loads((d / "manifest.json").read_text())
        panels = []
        titles = {"D1": "D1 ~1 um: source near crosshair is a background star (does not move)",
                  "D6": "D6 ~4.6 um: WISE 0855 (moves as predicted, see /validation)"}
        for band in ("D1", "D6"):
            if band in m["bands"]:
                a = load_cube(d, band, "all", m["shape"])[0]
                bd = m["bands"][band]
                wl = bd["all"]["wav"]
                panels.append(frame(a, bd["stretch"]["all"],
                                    f"{band} all epochs ({bd['all']['n']} exp)  {wl[0]:.2f}-{wl[1]:.2f} um" if wl else band,
                                    titles[band]))
        if len(panels) == 2:
            out = Image.new("RGB", (SIZE * 2 + 8, SIZE), (40, 40, 40))
            out.paste(panels[0], (0, 0))
            out.paste(panels[1], (SIZE + 8, 0))
            out.save(OUT / "wise0855_D1_vs_D6.png")
            made.append("wise0855_D1_vs_D6.png")
    bz = ROOT / "phase1_out" / "barnard_visit_blink_D1_display_saturated_zoom.gif"
    if bz.exists():
        (OUT / "barnard_D1_zoom_display_saturated.gif").write_bytes(bz.read_bytes())
    print("demo/:", "; ".join(made))


if __name__ == "__main__":
    main()
