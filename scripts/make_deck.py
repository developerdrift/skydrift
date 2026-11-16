# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""7-slide demo deck -> demo/SkyDrift_demo.pdf (16:9, matplotlib only).

Images are real SkyDrift renders of SPHEREx data (phase1_out/, docs/data/, demo/, validation plot).
Numbers are copied from PROGRESS.md "Final numbers" (final snapshot, 2026-11-15).
Usage: python scripts/make_deck.py [--png-dir DIR]   (PNG copies of each slide for checking)
"""
import argparse
import json
import sys
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import render  # noqa: E402

W, H = 13.333, 7.5
PINK, WHITE, MUTED, AMBER = "#FD91CC", "#FFFFFF", "#D6E0FA", "#FFD98A"
FONT, LIGHT = "Segoe UI", "Segoe UI Light"
plt.rcParams.update({"font.family": [FONT, "DejaVu Sans"], "pdf.fonttype": 42})
RNG = np.random.default_rng(7)
STARS = (RNG.uniform(0, 1, 160), RNG.uniform(0, 1, 160) ** 0.6, RNG.uniform(0.2, 2.2, 160), RNG.uniform(.25, .9, 160))


def slide():
    fig = plt.figure(figsize=(W, H), dpi=100)
    bg = fig.add_axes([0, 0, 1, 1])
    g = np.linspace(0, 1, 256)[:, None]
    top, mid, bot = np.array([2, 4, 12]) / 255, np.array([4, 16, 46]) / 255, np.array([7, 30, 92]) / 255
    col = np.where(g < .55, top + (mid - top) * (g / .55), mid + (bot - mid) * ((g - .55) / .45))
    bg.imshow(np.repeat(col[:, None, :], 2, axis=1).reshape(256, 2, 3), aspect="auto", extent=[0, 1, 0, 1])
    x, y, s, a = STARS
    bg.scatter(x, 1 - y * .9, s=s, c="white", alpha=a, linewidths=0)
    bg.set_xlim(0, 1)
    bg.set_ylim(0, 1)
    bg.axis("off")
    return fig, bg


def title(bg, text, kicker=None):
    if kicker:
        bg.text(.05, .915, kicker.upper(), color=PINK, fontsize=12, fontweight="semibold", va="center")
    bg.text(.05, .845, text, color=WHITE, fontsize=34, family=LIGHT, va="center")
    bg.plot([.05, .30], [.785, .785], color=PINK, lw=2.2, solid_capstyle="round")


def para(bg, x, y, text, width=48, size=15, color=WHITE, gap=1.45):
    lines = []
    for block in text.split("\n"):
        lines += textwrap.wrap(block, width) or [""]
    for i, ln in enumerate(lines):
        bg.text(x, y - i * gap * size / 72 / H, ln, color=color, fontsize=size, va="top")
    return y - len(lines) * gap * size / 72 / H


def bullets(bg, x, y, items, width=46, size=15):
    for it in items:
        bg.text(x, y, "•", color=PINK, fontsize=size, va="top")
        y = para(bg, x + .018, y, it, width, size) - .018
    return y


def image(fig, rect, arr_or_path, caption=None, cap_color=MUTED):
    ax = fig.add_axes(rect)
    img = np.asarray(Image.open(arr_or_path).convert("RGB")) if isinstance(arr_or_path, (str, Path)) else arr_or_path
    ax.imshow(img, interpolation="nearest")
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color((1, 1, 1, .35))
    if caption:
        ax.set_title(caption, color=cap_color, fontsize=12, pad=6)
    return ax


def gif_frames(path):
    im = Image.open(path)
    out = []
    try:
        while True:
            out.append(np.asarray(im.convert("RGB")).copy())
            im.seek(im.tell() + 1)
    except EOFError:
        pass
    return out


def crop_center(a, frac=.62):
    h, w = a.shape[:2]
    ch, cw = int(h * frac), int(w * frac)
    y0, x0 = 14 + (h - 14 - ch) // 2, (w - cw) // 2   # skip the 14-px label strip
    return a[y0:y0 + ch, x0:x0 + cw]


def load_view(key):
    d = ROOT / "docs" / "data" / key
    return d, json.loads((d / "manifest.json").read_text())


def exp_frames(d, m, band):
    h, w = m["shape"]
    enc = m["bands"][band]["enc"]["exp"]
    q = np.fromfile(d / f"{band}_exp.i16", "<i2").reshape(-1, h, w)
    return [np.where(q[k] == -32768, np.nan, enc["offset"][k] + (q[k] + 32500.0) * enc["scale"][k])
            for k in range(len(q))]


def to_rgb(a, st):
    return np.asarray(render.frame_image(a, st, "", scale=3, crosshair=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png-dir", default=None)
    a = ap.parse_args()
    out = ROOT / "demo" / "SkyDrift_demo.pdf"
    figs = []

    # 1 Title
    fig, bg = slide()
    bg.text(.07, .60, "◐", color=PINK, fontsize=64, va="center")
    bg.text(.15, .60, "SkyDrift", color=WHITE, fontsize=72, family=LIGHT, va="center")
    bg.plot([.07, .55], [.47, .47], color=PINK, lw=2.4, solid_capstyle="round")
    bg.text(.07, .40, "Blink SPHEREx images of any patch of sky.\nWatch what moves, and what changes.",
            color=MUTED, fontsize=22, va="top", linespacing=1.4)
    bg.text(.07, .13, "NASA Space Apps 2026: Planet X and SPHEREx", color=PINK, fontsize=18, fontweight="semibold")
    figs.append(fig)

    # 2 What it does
    fig, bg = slide()
    title(bg, "What it does", "The problem")
    y = para(bg, .05, .72, "SPHEREx images the whole sky at 0.75–5 µm, over and over. Somewhere in those "
             "images are nearby stars and brown dwarfs that drift between visits, and objects that change "
             "brightness. Finding them by flipping through hundreds of exposures by eye does not scale.",
             width=92, size=17)
    bg.text(.05, y - .04, "SkyDrift's answer", color=PINK, fontsize=15, fontweight="semibold", va="top")
    bullets(bg, .05, y - .11, [
        "Enter a position (or tap a preset): it collects every SPHEREx exposure of that spot.",
        "A wavelength-fair visit blink, so only real changes show.",
        "It flags movers and variables itself, measures them, and checks its own measurements "
        "against known stars.",
        "Runs locally, or as a static site of five pre-built presets."], width=90, size=16)
    figs.append(fig)

    # 3 Barnard's Star
    fig, bg = slide()
    title(bg, "Barnard's Star moves", "Real SPHEREx data, detector D1")
    fr = gif_frames(ROOT / "phase1_out" / "barnard_visit_blink_D1_display_saturated.gif")
    image(fig, [.05, .13, .36, .60], crop_center(fr[0], .9), "Visit 1: 2025-09-09")
    image(fig, [.43, .13, .36, .60], crop_center(fr[-1], .9), "Visit 2: 2026-03-11 (+183 d)")
    y = para(bg, .815, .72, "Measured shift", width=18, size=13, color=MUTED)
    bg.text(.815, y - .01, "6.52″", color=PINK, fontsize=36, family=LIGHT, va="top")
    y = para(bg, .815, y - .13, "predicted 5.22″ over 183 days (literature proper motion)", width=20, size=13)
    y = para(bg, .815, y - .03, "Neighbour stars moved a median 0.41″.", width=20, size=13)
    para(bg, .815, y - .03, "Barnard's Star is saturated: its core is shown with saturation flags "
         "unmasked, for display only, so the measurement is approximate.", width=20, size=11.5, color=AMBER)
    bg.text(.05, .07, "Crosshair = same sky position in both frames. North up, east left. One pixel = 3.1″.",
            color=MUTED, fontsize=11.5)
    figs.append(fig)

    # 4 Wavelength-fair blink
    fig, bg = slide()
    title(bg, "Wavelength-fair blink", "Why raw exposures flicker")
    d, m = load_view("r_dra")
    band = "D1"
    ex = exp_frames(d, m, band)
    meta = m["bands"][band]["exposures"]
    v0 = [k for k, e in enumerate(meta) if e["visit"] == meta[0]["visit"] and e["wav"]]
    pick = [v0[0], v0[len(v0) // 2], v0[-1]] if len(v0) >= 3 else v0[:3]
    st = m["bands"][band]["stretch"]["exp"]
    for i, k in enumerate(pick):
        image(fig, [.05 + i * .195, .37, .18, .30], crop_center(to_rgb(ex[k], st), .8)[14:],
              f"{meta[k]['wav']:.3f} µm")
    h, w = m["shape"]
    vis = np.fromfile(d / f"{band}_visits.f32", "<f4").reshape(-1, h, w)
    vm = m["bands"][band]["visits"][0]
    image(fig, [.66, .37, .29, .30], crop_center(to_rgb(vis[0], m["bands"][band]["stretch"]["visits"]), .8)[14:],
          f"Visit stack: {vm['n']} exposures, {vm['wav'][0]:.2f}–{vm['wav'][1]:.2f} µm")
    bg.text(.05, .735, "Single exposures, one visit of R Draconis (D1)", color=MUTED, fontsize=12.5)
    bg.text(.62, .52, "→", color=PINK, fontsize=34, va="center")
    bullets(bg, .05, .30, [
        "SPHEREx's filters vary across each detector, so every exposure sees a given star at a "
        "different wavelength. Blinking raw exposures flickers for that reason alone.",
        "SkyDrift stacks each detector per visit (inverse-variance weighted) on a common north-up "
        "grid, with one shared stretch, so only real motion or brightness change survives the blink."],
            width=118, size=14.5)
    figs.append(fig)

    # 5 Measuring what moves: WISE 0855
    fig, bg = slide()
    title(bg, "Measuring what moves", "WISE 0855-0714, the coldest known brown dwarf")
    image(fig, [.05, .33, .56, .42], ROOT / "demo" / "wise0855_D1_vs_D6.png")
    bg.text(.09, .305, "Left: D1, ~1 µm. The source near the crosshair is a background star.", color=MUTED, fontsize=11.5, va="top")
    bg.text(.09, .27, "Right: D6, ~4.6 µm. WISE 0855 itself.", color=MUTED, fontsize=11.5, va="top")
    bg.text(.65, .74, "Motion in D6 (4.6 µm)", color=MUTED, fontsize=13, va="top")
    bg.text(.65, .695, "4.07″", color=PINK, fontsize=38, family=LIGHT, va="top")
    y = para(bg, .65, .585, "measured, vs 4.61″ predicted from proper motion + parallax; "
             "position angle 281° vs 277°.", width=36, size=13.5)
    y = para(bg, .65, y - .025, "The candidate finder recovered it automatically as the field's known "
             "target and ranked it in the candidates list.", width=36, size=13.5)
    para(bg, .05, .205, "Provisional: invisible at ~1 µm, visible at ~4.6 µm. Only two D6 visits; a "
         "background star ~9″ away blends into short-wavelength measurements; the reference epoch of the "
         "challenge coordinates was inferred from the data; proper motion is a literature value, not live "
         "Gaia. D3 and D5 do not match the prediction (D3 is the neighbour star).",
         width=128, size=13, color=AMBER)
    figs.append(fig)

    # 6 Truth check
    fig, bg = slide()
    title(bg, "Truth check", "Does it measure known motions correctly?")
    image(fig, [.03, .10, .60, .64], ROOT / "app" / "static" / "validation" / "truth_plot.png")
    bg.text(.66, .74, "Final snapshot", color=MUTED, fontsize=13, va="top")
    bg.text(.66, .70, "48", color=PINK, fontsize=40, family=LIGHT, va="top")
    bg.text(.725, .655, "measurements of 29 stars", color=WHITE, fontsize=14, va="center")
    y = para(bg, .66, .585, "35 consistent with the prediction within 3σ.", width=38, size=13)
    y = para(bg, .66, y - .015, "RMS vector residual 0.85″ (consistent) and 1.86″ (all, outliers kept). "
             "One SPHEREx pixel = 6.2″.", width=38, size=13)
    y = para(bg, .66, y - .015, "Unsaturated stars only: 32 measurements of 18 stars, 25 consistent; "
             "RMS 0.81″ / 1.38″.", width=38, size=13)
    para(bg, .66, y - .03, "Limits: comparison values are literature proper motions and parallaxes, not "
         "live Gaia DR3 (IRSA's Gaia service was down). Coverage comes from a sampled S3 scan. "
         "Outliers are kept, not tuned away.", width=42, size=11.5, color=AMBER)
    figs.append(fig)

    # 7 Credits and disclosure
    fig, bg = slide()
    title(bg, "Credits and disclosure")
    y = para(bg, .05, .72, "This publication makes use of data products from the Spectro-Photometer for the "
             "History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint "
             "project of the Jet Propulsion Laboratory and the California Institute of Technology, and is "
             "funded by the National Aeronautics and Space Administration. Data: SPHEREx DR1 and QR3 spectral "
             "images from the NASA/IPAC Infrared Science Archive (IRSA).", width=118, size=13.5, color=MUTED)
    bg.text(.05, y - .05, "AI-assisted, human-directed: Claude Code wrote the code.", color=WHITE,
            fontsize=17, va="top")
    para(bg, .05, y - .11, "No AI-generated images: every picture is SPHEREx data rendered by SkyDrift.",
         width=118, size=13.5, color=MUTED)
    bg.text(.05, .25, "Live site", color=MUTED, fontsize=13)
    bg.text(.05, .195, "https://developerdrift.github.io/skydrift/", color=PINK, fontsize=19)
    bg.text(.05, .125, "Repository", color=MUTED, fontsize=13)
    bg.text(.05, .07, "https://github.com/developerdrift/skydrift", color=PINK, fontsize=19)
    figs.append(fig)

    with PdfPages(out, metadata={"Title": "SkyDrift demo", "Author": "SkyDrift team",
                                 "Creator": "matplotlib", "Producer": "matplotlib"}) as pdf:
        for i, f in enumerate(figs, 1):
            pdf.savefig(f)
            if a.png_dir:
                f.savefig(Path(a.png_dir) / f"slide{i}.png", dpi=60)
            plt.close(f)
    print(out, len(figs), "slides")


if __name__ == "__main__":
    main()
