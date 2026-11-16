# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Automatic mover / variable candidates from per-visit stacks of one detector.

Method (per detector with >= 2 visits):
1. Detect sources in every visit stack with `sep` (local background removed, 5 sigma from the
   VARIANCE-derived error map); windowed centroids; aperture fluxes (r = 3 grid px = 9.3").
2. Match first and last visit (largest time baseline), mutual nearest neighbour within 6 px.
3. Remove the field's median offset (sigma-clipped), so pointing/WCS shifts cancel.
4. MOVER: residual shift > k * sigma, with sigma per axis = sqrt(centroid_err_1^2 +
   centroid_err_2^2 + field_scatter^2), field_scatter = robust std of all residuals.
   Confirmed if the difference image (last - first) shows a + lobe at the new position and a
   - lobe at the old one (dipole), each > 3 sigma.
5. VARIABLE: log flux ratio (last/first) relative to the field median ratio > k * sigma.
   Visits in one detector see slightly different wavelengths; dividing by the field median
   removes the common part of that, not differences between unusual and typical spectra.
Candidates are not discoveries. Without a live Gaia cross-match (IRSA TAP down) only the
preset's own target can be called "known", using literature proper motion.
"""
import numpy as np
import sep
from astropy.stats import sigma_clipped_stats
from scipy.spatial import cKDTree

K_SIGMA = 5.0
AP_R = 3.0
MATCH_R = 6.0
FWHM_PX = 2.0   # SPHEREx PSF ~6" on the 3.1"/px grid


def detect(img, var, thresh=5.0, minarea=4):
    mask = ~np.isfinite(img) | ~np.isfinite(var) | (var <= 0)
    if mask.all():
        return None
    d = np.ascontiguousarray(np.where(mask, 0.0, img), dtype=np.float64)
    medv = np.median(var[~mask])
    e = np.ascontiguousarray(np.sqrt(np.where(mask, medv, var)), dtype=np.float64)
    bw = max(16, min(32, d.shape[0] // 3))
    bkg = sep.Background(d, mask=mask, bw=bw, bh=bw, fw=3, fh=3)
    d = d - bkg.back()
    try:
        o = sep.extract(d, thresh, err=e, mask=mask, minarea=minarea, deblend_cont=0.005)
    except Exception:  # noqa: BLE001  (sep can overflow on huge fields; skip then)
        return None
    if len(o) == 0:
        return None
    x, y, _ = sep.winpos(d, o["x"], o["y"], np.full(len(o), 1.0), mask=mask)
    flux, ferr, _ = sep.sum_circle(d, x, y, AP_R, err=e, mask=mask)
    # fraction of masked pixels inside the aperture -> drop sources sitting on holes / edges
    yy, xx = np.mgrid[:d.shape[0], :d.shape[1]]
    bad = np.array([mask[(np.hypot(xx - xi, yy - yi) <= AP_R)].mean() for xi, yi in zip(x, y)])
    edge = (x < 4) | (y < 4) | (x > d.shape[1] - 5) | (y > d.shape[0] - 5)
    keep = (bad < 0.15) & ~edge & (flux > 0)
    snr = flux / np.maximum(ferr, 1e-30)
    sx = np.sqrt(np.clip(o["errx2"], 0, None))
    sy = np.sqrt(np.clip(o["erry2"], 0, None))
    # sep returns inf/nan centroid variance for some very bright profiles. Fall back to the
    # standard estimate FWHM / (2.355 * S/N) (FWHM ~ 2 grid px), never to an infinite sigma.
    fb = FWHM_PX / (2.355 * np.maximum(snr, 1.0))
    sx = np.maximum(np.where(np.isfinite(sx), sx, fb), 0.03)
    sy = np.maximum(np.where(np.isfinite(sy), sy, fb), 0.03)
    return dict(x=x[keep], y=y[keep], flux=flux[keep], ferr=ferr[keep], sx=sx[keep],
                sy=sy[keep], snr=snr[keep], _d=d, _e=e, _mask=mask)


def forced(det, x, y, max_move=3.0, min_snr=10.0, max_bad=0.3):
    """Windowed centroid + aperture flux at a KNOWN position (used only for preset/truth targets
    that sep did not extract, e.g. blended). Returns a measurement dict or None."""
    if det is None:
        return None
    d, e, mask = det["_d"], det["_e"], det["_mask"]
    xw, yw, _ = sep.winpos(d, np.array([x], float), np.array([y], float), np.array([1.0]), mask=mask)
    xw, yw = float(xw[0]), float(yw[0])
    if not (np.isfinite(xw) and np.hypot(xw - x, yw - y) < max_move):
        return None
    yy, xx = np.mgrid[:d.shape[0], :d.shape[1]]
    if mask[np.hypot(xx - xw, yy - yw) <= AP_R].mean() > max_bad:
        return None
    f, fe, _ = sep.sum_circle(d, np.array([xw]), np.array([yw]), AP_R, err=e, mask=mask)
    snr = float(f[0] / max(fe[0], 1e-30))
    if snr < min_snr:
        return None
    sig = max(FWHM_PX / (2.355 * snr), 0.03)
    return dict(x=xw, y=yw, flux=float(f[0]), ferr=float(fe[0]), sx=sig, sy=sig, snr=snr)


def _mutual_match(a, b, r=MATCH_R):
    if a is None or b is None or len(a["x"]) == 0 or len(b["x"]) == 0:
        return np.array([], int), np.array([], int)
    pa, pb = np.c_[a["x"], a["y"]], np.c_[b["x"], b["y"]]
    dab, iab = cKDTree(pb).query(pa, distance_upper_bound=r)
    _, iba = cKDTree(pa).query(pb, distance_upper_bound=r)
    ia = [i for i, j in enumerate(iab) if j < len(pb) and iba[j] == i]
    return np.array(ia, int), iab[ia].astype(int)


def _ap(img, var, x, y, r=2.0):
    yy, xx = np.mgrid[:img.shape[0], :img.shape[1]]
    m = (np.hypot(xx - x, yy - y) <= r) & np.isfinite(img) & np.isfinite(var)
    if m.sum() < 3:
        return np.nan, np.nan
    return float(img[m].sum()), float(np.sqrt(var[m].sum()))


def _dipole(diff, dvar, x1, y1, x0, y0):
    p, pe = _ap(diff, dvar, x1, y1)
    m, me = _ap(diff, dvar, x0, y0)
    ok = bool(pe and me and np.isfinite(p) and np.isfinite(m) and p / pe > 3 and m / me < -3)
    return dict(dipole=dict(plus_sigma=round(p / pe, 1) if pe and np.isfinite(p) else None,
                            minus_sigma=round(m / me, 1) if me and np.isfinite(m) else None),
                dipole_confirmed=ok)


def _measure_target(target, d0, d1, ox, oy, scat, s0, s1, diff, dvar, wcs, scale, dt_yr, r=3.0,
                    var_ref=None):
    """Always report the preset's own star: nearest detections to its predicted positions."""
    how = []

    def near(d, xy):
        """Extracted source within r of the prediction, else a forced measurement there."""
        if d is not None and len(d["x"]):
            dist = np.hypot(d["x"] - xy[0], d["y"] - xy[1])
            i = int(np.argmin(dist))
            if dist[i] < r:
                how.append("extracted")
                return {k: (float(d[k][i])) for k in ("x", "y", "flux", "ferr", "sx", "sy", "snr")}
        m = forced(d, float(xy[0]), float(xy[1]))
        if m:
            how.append("forced")
        return m
    m0, m1 = near(d0, target["xy_first"]), near(d1, target["xy_last"])
    base = dict(kind="known target", known=True, score=1e3)
    if m0 is None or m1 is None:
        return dict(base, x=round(float(target["xy_last"][0]), 2), y=round(float(target["xy_last"][1]), 2),
                    label=f"known: {target['name']} - not detected in both visits of this detector")
    rx, ry = m1["x"] - m0["x"] - ox, m1["y"] - m0["y"] - oy
    sx = np.sqrt(m0["sx"] ** 2 + m1["sx"] ** 2 + scat ** 2)
    sy = np.sqrt(m0["sy"] ** 2 + m1["sy"] ** 2 + scat ** 2)
    shift = float(np.hypot(rx, ry) * scale)
    pred = np.array(target["xy_last"]) - np.array(target["xy_first"])
    err = float(np.hypot(sx, sy) * scale / np.sqrt(2))
    x1, y1 = m1["x"], m1["y"]
    ra, dec = wcs.wcs_pix2world([[x1, y1]], 0)[0]
    c = dict(base, x=round(x1, 2), y=round(y1, 2), x0=round(m0["x"], 2), y0=round(m0["y"], 2),
             ra=round(float(ra), 6), dec=round(float(dec), 6), centroids="+".join(how),
             snr=round(float(min(m0["snr"], m1["snr"])), 1), shift_arcsec=round(shift, 2),
             shift_err_arcsec=round(err, 2), pred_shift_arcsec=round(target["pred_shift_arcsec"], 2),
             pm_arcsec_yr=round(shift / dt_yr, 2) if dt_yr > 0 else None,
             pa_deg=round(float(np.degrees(np.arctan2(-rx, ry)) % 360), 1),
             pred_pa_deg=round(float(np.degrees(np.arctan2(-pred[0], pred[1])) % 360), 1),
             move_sigma=round(float(np.hypot(rx / sx, ry / sy)), 1),
             flux_ratio=round(float(m1["flux"] / m0["flux"]), 3))
    c["meas_dxdy_arcsec"] = [round(float(-rx * scale), 3), round(float(ry * scale), 3)]   # (east, north)
    c["pred_dxdy_arcsec"] = [round(float(-pred[0] * scale), 3), round(float(pred[1] * scale), 3)]
    c["err_xy_arcsec"] = [round(float(sx * scale), 3), round(float(sy * scale), 3)]
    c.update(_dipole(diff, dvar, x1, y1, c["x0"], c["y0"]))
    # Is the measured motion vector consistent with the prediction? (3 sigma per axis)
    mis = np.hypot((rx - pred[0]) / sx, (ry - pred[1]) / sy)
    c["matches_prediction"] = bool(mis < 3.0)
    c["label"] = (f"known: {target['name']} ({target['pm_note']}). Predicted shift {c['pred_shift_arcsec']:.2f}\" "
                  f"at PA {c['pred_pa_deg']:.0f}; measured {shift:.2f} +/- {err:.2f}\" at PA {c['pa_deg']:.0f} "
                  f"({c['move_sigma']:.1f} sigma)")
    if not c["matches_prediction"]:
        c["label"] = (f"source near {target['name']}'s predicted position, but its motion does not match "
                      f"the prediction ({mis:.1f} sigma off) - probably a neighbour, not the target. "
                      f"Measured {shift:.2f}\" at PA {c['pa_deg']:.0f}; predicted {c['pred_shift_arcsec']:.2f}\" "
                      f"at PA {c['pred_pa_deg']:.0f}")
        c["kind"] = "near target (not matched)"
    if var_ref is not None:
        lmed, lscat, wav_matched, k = var_ref
        lr = np.log(m1["flux"] / m0["flux"])
        ls = np.sqrt((m0["ferr"] / m0["flux"]) ** 2 + (m1["ferr"] / m1["flux"]) ** 2 + lscat ** 2)
        c["flux_ratio"] = round(float(np.exp(lr - lmed)), 3)
        c["var_sigma"] = round(float((lr - lmed) / ls), 1)
        if wav_matched and abs(c["var_sigma"]) > k:
            c["label"] += (f". VARIABLE: flux x{c['flux_ratio']:.2f} relative to the field "
                           f"({c['var_sigma']:.1f} sigma, wavelength ranges overlap)")
            c["variable"] = True
    return c


def find(stacks, wcs, scale_arcsec, target=None, k=K_SIGMA):
    """stacks: visit stacks of one detector (dicts with img, var, mjd_mean, wav_range), time order.
    target: optional dict(name, xy_first, xy_last, pm_note) for the preset's known star.
    Returns (candidates, summary)."""
    if len(stacks) < 2:
        return [], dict(note="needs >= 2 visits")
    s0, s1 = stacks[0], stacks[-1]
    d0, d1 = detect(s0["img"], s0["var"]), detect(s1["img"], s1["var"])
    if d0 is None or d1 is None:
        return [], dict(note="no detections")
    i0, i1 = _mutual_match(d0, d1)
    summ = dict(n_first=len(d0["x"]), n_last=len(d1["x"]), n_matched=int(len(i0)),
                baseline_days=round(s1["mjd_mean"] - s0["mjd_mean"], 1))
    if len(i0) < 4:
        summ["note"] = "too few matched sources for a field offset"
        return [], summ
    dx, dy = d1["x"][i1] - d0["x"][i0], d1["y"][i1] - d0["y"][i0]
    _, ox, _ = sigma_clipped_stats(dx, sigma=3)
    _, oy, _ = sigma_clipped_stats(dy, sigma=3)
    rx, ry = dx - ox, dy - oy
    core = np.hypot(rx, ry) < 1.5
    scat = 1.4826 * np.median(np.abs(np.r_[rx[core], ry[core]])) if core.sum() >= 3 else 0.3
    sigx = np.sqrt(d0["sx"][i0] ** 2 + d1["sx"][i1] ** 2 + scat ** 2)
    sigy = np.sqrt(d0["sy"][i0] ** 2 + d1["sy"][i1] ** 2 + scat ** 2)
    chi = np.hypot(rx / sigx, ry / sigy)
    # flux ratios
    lr = np.log(d1["flux"][i1] / d0["flux"][i0])
    _, lmed, _ = sigma_clipped_stats(lr[core], sigma=3) if core.sum() >= 3 else (0, np.median(lr), 0)
    lscat = 1.4826 * np.median(np.abs(lr[core] - lmed)) if core.sum() >= 3 else 0.1
    lsig = np.sqrt((d0["ferr"][i0] / d0["flux"][i0]) ** 2 + (d1["ferr"][i1] / d1["flux"][i1]) ** 2 + lscat ** 2)
    vchi = (lr - lmed) / lsig
    summ.update(field_offset_px=[round(float(ox), 3), round(float(oy), 3)],
                field_scatter_arcsec=round(float(scat * scale_arcsec), 3),
                flux_ratio_median=round(float(np.exp(lmed)), 3), flux_scatter_dex=round(float(lscat / np.log(10)), 3))
    w0, w1 = s0.get("wav_range", (np.nan, np.nan)), s1.get("wav_range", (np.nan, np.nan))
    inter = max(0.0, min(w0[1], w1[1]) - max(w0[0], w1[0]))
    union = max(w0[1], w1[1]) - min(w0[0], w1[0])
    wav_overlap = float(inter / union) if np.isfinite(union) and union > 0 else 0.0
    wav_matched = wav_overlap >= 0.5
    summ.update(wav_first=[round(float(x), 3) for x in w0], wav_last=[round(float(x), 3) for x in w1],
                wav_overlap=round(wav_overlap, 2), variables_allowed=bool(wav_matched))
    diff = s1["img"] - s0["img"]
    dvar = s1["var"] + s0["var"]
    dt_yr = (s1["mjd_mean"] - s0["mjd_mean"]) / 365.25
    out = []
    for n, (a, b) in enumerate(zip(i0, i1)):
        snr = float(min(d0["snr"][a], d1["snr"][b]))
        shift = float(np.hypot(rx[n], ry[n]) * scale_arcsec)
        is_mover = chi[n] > k and shift > 1.5 and snr > 10
        is_var = (wav_matched and not is_mover and abs(vchi[n]) > k and snr > 10
                  and np.hypot(rx[n], ry[n]) < 1.5)
        if not (is_mover or is_var):
            continue
        x1, y1 = float(d1["x"][b]), float(d1["y"][b])
        ra, dec = wcs.wcs_pix2world([[x1, y1]], 0)[0]
        c = dict(kind="mover" if is_mover else "variable", x=round(x1, 2), y=round(y1, 2),
                 x0=round(float(d0["x"][a]), 2), y0=round(float(d0["y"][a]), 2),
                 ra=round(float(ra), 6), dec=round(float(dec), 6), snr=round(snr, 1),
                 shift_arcsec=round(shift, 2),
                 pm_arcsec_yr=round(shift / dt_yr, 2) if dt_yr > 0 else None,
                 pa_deg=round(float(np.degrees(np.arctan2(-rx[n], ry[n])) % 360), 1),  # E of N (x flipped: E left)
                 move_sigma=round(float(chi[n]), 1),
                 flux_ratio=round(float(np.exp(lr[n] - lmed)), 3), var_sigma=round(float(vchi[n]), 1))
        if is_mover:
            c.update(_dipole(diff, dvar, x1, y1, c["x0"], c["y0"]))
        c["score"] = round(float(chi[n] if is_mover else abs(vchi[n])), 1)
        c["label"] = "unverified candidate - no live Gaia cross-match (IRSA TAP down); needs checking"
        if target is not None and np.hypot(x1 - target["xy_last"][0], y1 - target["xy_last"][1]) < 3.0:
            continue  # reported below as the known target
        if is_mover and not c["dipole_confirmed"]:
            c["label"] = "unconfirmed: no +/- dipole in the difference image; " + c["label"]
        out.append(c)
    if target is not None:
        t = _measure_target(target, d0, d1, ox, oy, scat, s0, s1, diff, dvar, wcs, scale_arcsec, dt_yr,
                            var_ref=(lmed, lscat, wav_matched, k))
        if t:
            out.append(t)
    out.sort(key=lambda c: -c["score"])
    summ["n_movers"] = sum(c["kind"] == "mover" for c in out)
    summ["n_variables"] = sum(c["kind"] == "variable" for c in out)
    return out, summ
