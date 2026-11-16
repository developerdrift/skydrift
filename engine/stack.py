# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Inverse-variance weighted stacks per (visit, detector), plus an all-epoch stack."""
from collections import defaultdict

import numpy as np


def ivw(scis, vars_):
    """Inverse-variance mean. Returns (image, variance, n_contributing) with NaN where empty."""
    num = np.zeros_like(scis[0], dtype=np.float64)
    den = np.zeros_like(num)
    n = np.zeros(num.shape, int)
    for s, v in zip(scis, vars_):
        ok = np.isfinite(s) & np.isfinite(v) & (v > 0)
        w = np.where(ok, 1.0 / np.where(ok, v, 1.0), 0.0)
        num += np.where(ok, s, 0.0) * w
        den += w
        n += ok
    with np.errstate(invalid="ignore", divide="ignore"):
        img = np.where(den > 0, num / den, np.nan)
        var = np.where(den > 0, 1.0 / den, np.nan)
    return img, var, n


def group_stacks(frames, key=lambda f: (f["visit"], f["band"])):
    """frames: dicts with sci, var, mjd, wav, band, visit, planeid. Returns sorted stack dicts."""
    groups = defaultdict(list)
    for f in frames:
        groups[key(f)].append(f)
    out = []
    for k, fs in groups.items():
        img, var, n = ivw([f["sci"] for f in fs], [f["var"] for f in fs])
        wav = [f["wav"] for f in fs if np.isfinite(f.get("wav", np.nan))]
        out.append(dict(
            key=k, img=img, var=var, nmap=n, n=len(fs),
            band=fs[0]["band"], visit=fs[0].get("visit"),
            mjd_mean=float(np.mean([f["mjd"] for f in fs])),
            mjd_range=(float(min(f["mjd"] for f in fs)), float(max(f["mjd"] for f in fs))),
            wav_range=(min(wav), max(wav)) if wav else (np.nan, np.nan),
            planeids=[f["planeid"] for f in fs],
        ))
    out.sort(key=lambda s: s["mjd_mean"])
    return out


def all_epoch(frames):
    img, var, n = ivw([f["sci"] for f in frames], [f["var"] for f in frames])
    return dict(img=img, var=var, nmap=n, n=len(frames))
