# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Small measurement helpers (centroids) used by tests and later by candidate finding."""
import numpy as np


def centroid(img, x0, y0, r=4.0, iters=5):
    """Iterative background-subtracted first-moment centroid in a circular window."""
    yy, xx = np.mgrid[:img.shape[0], :img.shape[1]]
    good = np.isfinite(img)
    x, y = float(x0), float(y0)
    for _ in range(iters):
        rr = np.hypot(xx - x, yy - y)
        ann = good & (rr > r + 2) & (rr < r + 6)
        bkg = np.nanmedian(img[ann]) if ann.any() else 0.0
        w = np.where(good & (rr <= r), img - bkg, 0.0)
        w = np.clip(w, 0, None)
        tot = w.sum()
        if tot <= 0:
            return np.nan, np.nan
        x, y = float((w * xx).sum() / tot), float((w * yy).sum() / tot)
    return x, y
