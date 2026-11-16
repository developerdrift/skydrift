# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""One shared asinh stretch for every frame of a sequence, and GIF output."""
import numpy as np
from PIL import Image, ImageDraw


def shared_stretch(images, lo_pct=1.0, hi_pct=99.7, soft=0.05):
    vals = np.concatenate([a[np.isfinite(a)].ravel() for a in images if np.isfinite(a).any()])
    lo, hi = np.percentile(vals, [lo_pct, hi_pct])
    if hi <= lo:
        hi = lo + 1e-12
    return dict(lo=float(lo), hi=float(hi), soft=float(soft))


def to_u8(img, st):
    x = (np.clip(img, st["lo"], st["hi"]) - st["lo"]) / (st["hi"] - st["lo"])
    y = np.arcsinh(x / st["soft"]) / np.arcsinh(1.0 / st["soft"])
    y = np.where(np.isfinite(img), y, 0.0)
    return (np.clip(y, 0, 1) * 255).astype(np.uint8)


def frame_image(img, st, label="", scale=4, crosshair=True):
    """North up, east left: flip rows so array row 0 (south) is at the bottom."""
    a = to_u8(img, st)[::-1]
    im = Image.fromarray(a, "L").resize((a.shape[1] * scale, a.shape[0] * scale),
                                        Image.NEAREST).convert("RGB")
    d = ImageDraw.Draw(im)
    if crosshair:
        cx, cy = im.width / 2, im.height / 2
        g, L = 6 * scale / 2, 14 * scale / 2
        for (x0, y0, x1, y1) in [(cx - L, cy, cx - g, cy), (cx + g, cy, cx + L, cy),
                                 (cx, cy - L, cx, cy - g), (cx, cy + g, cx, cy + L)]:
            d.line([x0, y0, x1, y1], fill=(255, 80, 80), width=1)
    if label:
        d.rectangle([0, 0, im.width, 14], fill=(0, 0, 0))
        d.text((3, 1), label, fill=(255, 255, 255))
    return im


def write_gif(images, labels, path, st=None, scale=4, duration_ms=600, crosshair=True):
    st = st or shared_stretch(images)
    frames = [frame_image(a, st, lab, scale, crosshair) for a, lab in zip(images, labels)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=duration_ms,
                   loop=0, optimize=False)
    return st
