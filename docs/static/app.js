// AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
// SkyDrift blink player. Plain JS, no frameworks, no external requests.
// Live mode talks to the local server (/api/...). Static mode (GitHub Pages) reads data/.
"use strict";
const $ = (id) => document.getElementById(id);
const S = {
  mode: "live", presets: [], man: null, base: "", band: null, view: "visits",
  frames: [], meta: [], i: 0, playing: false, timer: null, zoom: 1, panX: 0, panY: 0,
  cache: new Map(), stretch: null, visitSel: 0, subA: 0, subB: 0,
};
const params = new URLSearchParams(location.search);
if (params.get("embed") === "1") document.body.classList.add("embed");

// ---------- startup ----------
async function init() {
  try {
    const r = await fetch("api/presets");
    if (!r.ok) throw new Error();
    const j = await r.json();
    S.presets = j.presets;
  } catch {
    S.mode = "static";
    const j = await (await fetch("data/presets.json")).json();
    S.presets = j.presets;
    $("staticnote").hidden = false;
    $("vallink").href = "validation.html";
    for (const id of ["ra", "dec", "fov", "go"]) $(id).disabled = true;
  }
  const box = $("presets");
  for (const p of S.presets) {
    const b = document.createElement("button");
    b.textContent = p.name; b.type = "button"; b.dataset.key = p.key;
    b.onclick = () => { setInputs(p.ra, p.dec, p.fov); S.wantBand = p.band; load(); };
    box.appendChild(b);
  }
  bindUI();
  if (params.get("ra") && params.get("dec")) {
    setInputs(params.get("ra"), params.get("dec"), params.get("fov") || 6);
    S.wantBand = params.get("band"); S.wantMode = params.get("mode");
    load();
  } else if (S.presets.length) {
    // Default view: the first preset (Barnard's Star, clearest motion) in Visit blink.
    const p = S.presets[0];
    setInputs(p.ra, p.dec, p.fov); S.wantBand = p.band; S.wantMode = "visits";
    load();
  }
}

function setInputs(ra, dec, fov) { $("ra").value = ra; $("dec").value = dec; $("fov").value = fov; }

// ---------- loading ----------
function showErr(msg) { $("err").textContent = msg; $("err").hidden = !msg; }
function progress(frac, text) {
  $("progress").hidden = frac === null;
  if (frac !== null) { $("pbar").style.width = `${Math.round(frac * 100)}%`; $("ptext").textContent = text || ""; }
}

async function load() {
  showErr("");
  const ra = String($("ra").value).trim(), dec = String($("dec").value).trim(), fov = String($("fov").value);
  for (const b of $("presets").children) b.classList.remove("on");
  try {
    if (S.mode === "static") {
      const p = S.presets.find((p) => Math.abs(p.ra - parseFloat(ra)) < 1e-4 && Math.abs(p.dec - parseFloat(dec)) < 1e-4);
      if (!p) throw new Error("The static showcase only has the five presets. Run the local server for other positions.");
      S.base = `data/${p.key}/`;
      markPreset(p.key);
    } else {
      progress(0.01, "starting");
      let j = await getJSON(`api/view?ra=${encodeURIComponent(ra)}&dec=${encodeURIComponent(dec)}&fov=${encodeURIComponent(fov)}`);
      while (j.status === "running") {
        await new Promise((r) => setTimeout(r, 700));
        const s = await getJSON(`api/job/${j.job}`);
        progress(s.frac, s.stage);
        if (s.status === "error") throw new Error(s.error);
        if (s.status === "done") j = s;
      }
      S.base = j.base;
      const p = S.presets.find((p) => Math.abs(p.ra - parseFloat(ra)) < 1e-4 && Math.abs(p.dec - parseFloat(dec)) < 1e-4);
      if (p) markPreset(p.key);
    }
    S.man = await getJSON(`${S.base}manifest.json?t=${Date.now()}`);
    S.specXY = null; $("specplot").hidden = true; $("lcplot").hidden = true;
    $("spectext").textContent = "Click a source on the image (or a marked candidate) to measure it in every exposure from all six detectors.";
    S.cov = null;
    if (S.mode === "live") getJSON(`api/coverage?ra=${S.man.ra}&dec=${S.man.dec}`).then((c) => { S.cov = c; metaPanel(); }).catch(() => {});
    S.cache.clear();
    progress(null);
    const bands = Object.keys(S.man.bands);
    if (!bands.length) throw new Error(S.man.empty_reason || "No usable SPHEREx exposures were found here.");
    $("band").innerHTML = bands.map((b) => `<option>${b}</option>`).join("");
    const nv = (b) => S.man.bands[b].visits.length;
    const most = bands.reduce((x, y) => (nv(y) > nv(x) ? y : x), bands[0]);
    S.band = bands.includes(S.wantBand) && (nv(S.wantBand) > 1 || S.wantMode) ? S.wantBand : most;
    $("band").value = S.band;
    if (S.wantMode) { $("mode").value = S.wantMode; S.view = S.wantMode; }
    S.wantBand = S.wantMode = null;
    $("viewer").hidden = false;
    S.zoom = 1; S.panX = S.panY = 0;
    await setView();
  } catch (e) { progress(null); showErr(e.message || String(e)); }
}

function markPreset(key) { for (const b of $("presets").children) b.classList.toggle("on", b.dataset.key === key); }

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.json();
}

async function cube(kind) {
  const key = `${S.band}_${kind}`, [h, w] = S.man.shape;
  if (!S.cache.has(key)) {
    const enc = (S.man.bands[S.band].enc || {})[kind];
    let a;
    if (enc && enc.type === "i16") {  // static showcase: int16 + per-frame linear scale
      const q = new Int16Array(await (await fetch(`${S.base}${key}.i16?v=${encodeURIComponent(S.man.built)}`)).arrayBuffer());
      a = new Float32Array(q.length);
      for (let k = 0; k < q.length; k++) {
        const f = Math.floor(k / (h * w));
        a[k] = q[k] === -32768 ? NaN : enc.offset[f] + (q[k] + 32500) * enc.scale[f];
      }
    } else a = new Float32Array(await (await fetch(`${S.base}${key}.f32?v=${encodeURIComponent(S.man.built)}`)).arrayBuffer());
    S.cache.set(key, a);
  }
  const a = S.cache.get(key), n = a.length / (h * w);
  return Array.from({ length: n }, (_, k) => a.subarray(k * h * w, (k + 1) * h * w));
}

// ---------- view assembly ----------
async function setView() {
  stop();
  const b = S.man.bands[S.band], v = S.view;
  $("visitpick").hidden = v !== "exposures";
  $("subpick").hidden = v !== "subtract";
  if (v === "visits") {
    S.frames = await cube("visits"); S.meta = b.visits.map((m) => ({ ...m, kind: "visit" }));
    S.stretch = b.stretch.visits;
  } else if (v === "exposures") {
    const vis = [...new Set(b.exposures.map((e) => e.visit))];
    $("visitsel").innerHTML = vis.map((x, k) => `<option value="${x}">${k + 1}: ${b.exposures.find((e) => e.visit === x).time.slice(0, 10)}</option>`).join("");
    if (!vis.includes(S.visitSel)) S.visitSel = vis[0];
    $("visitsel").value = S.visitSel;
    const all = await cube("exp");
    const idx = b.exposures.map((e, k) => (e.visit === S.visitSel ? k : -1)).filter((k) => k >= 0);
    S.frames = idx.map((k) => all[k]); S.meta = idx.map((k) => ({ ...b.exposures[k], kind: "exposure" }));
    S.stretch = b.stretch.exp;
  } else if (v === "add") {
    S.frames = await cube("all"); S.meta = [{ ...b.all, kind: "all" }]; S.stretch = b.stretch.all;
  } else {
    const vs = await cube("visits"), n = vs.length;
    if (n < 2) {
      S.frames = [new Float32Array(vs[0].length)]; S.meta = [{ kind: "diff1" }]; S.stretch = { diff: true, hi: 1, soft: 0.1 };
      S.i = 0; $("scrub").max = 0; syncURL(); draw(); return;
    }
    const opts = b.visits.map((m, k) => `<option value="${k}">${k + 1}: ${m.time.slice(0, 10)}</option>`).join("");
    $("suba").innerHTML = opts; $("subb").innerHTML = opts;
    if (S.subA >= n || S.subB >= n || S.subA === S.subB) { S.subA = n - 1; S.subB = 0; }
    $("suba").value = S.subA; $("subb").value = S.subB;
    const A = vs[S.subA], B = vs[S.subB], d = new Float32Array(A.length);
    for (let k = 0; k < A.length; k++) d[k] = A[k] - B[k];
    S.frames = [d];
    S.meta = [{ kind: "diff", a: b.visits[S.subA], b: b.visits[S.subB], n: n }];
    S.stretch = diffStretch(d);
  }
  S.selCand = -1; candPanel();
  S.i = Math.min(S.i, S.frames.length - 1); if (S.i < 0) S.i = 0;
  $("scrub").max = Math.max(0, S.frames.length - 1);
  syncURL();
  draw();
  if (S.frames.length > 1 && v !== "subtract") play();
}

function diffStretch(d) {
  const s = [];
  for (let k = 0; k < d.length; k += 3) if (Number.isFinite(d[k])) s.push(Math.abs(d[k]));
  s.sort((x, y) => x - y);
  const hi = s.length ? s[Math.floor(0.995 * (s.length - 1))] || 1 : 1;
  return { diff: true, hi, soft: 0.1 };
}

// ---------- rendering ----------
const off = document.createElement("canvas");
function draw() {
  const [h, w] = S.man.shape, f = S.frames[S.i];
  if (!f) return;
  off.width = w; off.height = h;
  const ctx = off.getContext("2d"), img = ctx.createImageData(w, h), st = S.stretch;
  const A = Math.asinh(1 / st.soft);
  for (let y = 0; y < h; y++) {
    const row = (h - 1 - y) * w; // row 0 of the data is south: flip so north is up
    for (let x = 0; x < w; x++) {
      const v = f[row + x], o = 4 * (y * w + x);
      let g;
      if (!Number.isFinite(v)) { img.data[o] = 28; img.data[o + 1] = 22; img.data[o + 2] = 40; img.data[o + 3] = 255; continue; }
      if (st.diff) g = 127.5 + 127.5 * Math.asinh(Math.max(-1, Math.min(1, v / st.hi)) / st.soft) / A;
      else { const t = Math.max(0, Math.min(1, (v - st.lo) / (st.hi - st.lo))); g = 255 * Math.asinh(t / st.soft) / A; }
      img.data[o] = img.data[o + 1] = img.data[o + 2] = g; img.data[o + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  const cv = $("stage"), c = cv.getContext("2d"), W = cv.width, H = cv.height;
  c.imageSmoothingEnabled = false;
  c.fillStyle = "#000"; c.fillRect(0, 0, W, H);
  const s = (W / w) * S.zoom;
  c.drawImage(off, W / 2 - (w / 2) * s + S.panX, H / 2 - (h / 2) * s + S.panY, w * s, h * s);
  if ($("cross").checked) {
    const cx = W / 2 + S.panX, cy = H / 2 + S.panY, g = 9 * S.zoom, L = 26 * S.zoom;
    c.strokeStyle = "rgba(253,145,204,.95)"; c.lineWidth = 1.5; c.beginPath();
    c.moveTo(cx - L, cy); c.lineTo(cx - g, cy); c.moveTo(cx + g, cy); c.lineTo(cx + L, cy);
    c.moveTo(cx, cy - L); c.lineTo(cx, cy - g); c.moveTo(cx, cy + g); c.lineTo(cx, cy + L); c.stroke();
  }
  if ($("marks").checked) drawMarks(c, W, H, w, h, s);
  if (S.specXY) {
    const [X, Y] = toScreen(S.specXY[0], S.specXY[1], W, H, w, h, s);
    c.strokeStyle = "#ffe066"; c.lineWidth = 1.5; c.beginPath();
    c.moveTo(X - 7, Y - 7); c.lineTo(X + 7, Y + 7); c.moveTo(X - 7, Y + 7); c.lineTo(X + 7, Y - 7); c.stroke();
  }
  // scale bar: 30 arcsec
  const px30 = (30 / S.man.scale_arcsec) * s;
  c.fillStyle = "#fff"; c.fillRect(W - 14 - px30, H - 16, px30, 3);
  c.font = "12px system-ui"; c.fillText('30"', W - 14 - px30, H - 22);
  c.fillText("N↑ E←", 10, H - 12);
  $("scrub").value = S.i;
  label(); metaPanel();
}

// ---------- candidates ----------
function toScreen(x, y, W, H, w, h, s) {
  return [W / 2 - (w / 2) * s + S.panX + (x + 0.5) * s, H / 2 - (h / 2) * s + S.panY + (h - 1 - y + 0.5) * s];
}
function candColor(c) {
  if (c.kind === "variable" || c.variable) return "rgba(245,194,107,.95)";
  if (c.kind === "near target (not matched)" || (c.kind === "mover" && !c.dipole_confirmed)) return "rgba(160,160,160,.9)";
  return "rgba(253,145,204,.95)";
}
function drawMarks(c, W, H, w, h, s) {
  const list = (S.man.bands[S.band] || {}).candidates || [];
  list.forEach((d, k) => {
    if (d.x == null) return;
    const [X, Y] = toScreen(d.x, d.y, W, H, w, h, s), r = Math.max(10, 4.5 * s);
    c.strokeStyle = candColor(d); c.lineWidth = k === S.selCand ? 2.5 : 1.5;
    c.beginPath(); c.arc(X, Y, r, 0, 2 * Math.PI); c.stroke();
    if (d.x0 != null && d.shift_arcsec > 0.5) {
      const [X0, Y0] = toScreen(d.x0, d.y0, W, H, w, h, s);
      c.beginPath(); c.moveTo(X0, Y0); c.lineTo(X, Y); c.stroke();
      c.beginPath(); c.arc(X0, Y0, 2, 0, 2 * Math.PI); c.fill();
    }
    c.fillStyle = candColor(d); c.font = "12px system-ui"; c.fillText(String(k + 1), X + r + 2, Y - r + 4);
  });
}
function candPanel() {
  const b = S.man.bands[S.band] || {}, list = b.candidates || [], sm = b.cand_summary || {};
  const fmt = (v, d = 2) => (v == null ? "–" : (+v).toFixed(d));
  let h = `<h3>Candidates in ${S.band}</h3>`;
  if (sm.note && !list.length) h += `<p class="fine">${sm.note}.</p>`;
  else h += `<p class="fine">First vs last visit (${sm.baseline_days ?? "–"} d apart): ${sm.n_matched ?? 0} matched sources,
    field scatter ${fmt(sm.field_scatter_arcsec)}″, wavelength overlap ${fmt(sm.wav_overlap)}
    ${sm.variables_allowed ? "" : "(too different for variability claims)"}. Threshold 5σ. Candidates are not discoveries.</p>`;
  if (!list.length && !sm.note) h += `<p class="fine">Nothing above threshold in this detector.</p>`;
  list.forEach((c, k) => {
    const cls = c.kind === "variable" || c.variable ? "var" : c.kind.startsWith("near") || (c.kind === "mover" && !c.dipole_confirmed) ? "bad" : "";
    h += `<div class="c ${k === S.selCand ? "sel" : ""}" data-k="${k}"><span class="tag ${cls}">${k + 1} · ${c.kind}${c.variable ? " · variable" : ""}</span>
      ${c.shift_arcsec != null ? `shift ${fmt(c.shift_arcsec)}″` : ""} ${c.pm_arcsec_yr != null ? `(${fmt(c.pm_arcsec_yr)}″/yr, PA ${fmt(c.pa_deg, 0)}°)` : ""}
      ${c.snr != null ? `S/N ${fmt(c.snr, 0)}` : ""} ${c.dipole ? `· dipole ${c.dipole_confirmed ? "✓" : "✗"} (+${fmt(c.dipole.plus_sigma, 1)}σ / ${fmt(c.dipole.minus_sigma, 1)}σ)` : ""}
      <div class="fine">${c.label}${c.ra != null ? ` · RA ${fmt(c.ra, 5)}° Dec ${fmt(c.dec, 5)}°` : ""}</div></div>`;
  });
  $("cands").innerHTML = h;
  for (const el of $("cands").querySelectorAll(".c")) el.onclick = () => focusCand(+el.dataset.k);
}
function focusCand(k) {
  const c = S.man.bands[S.band].candidates[k], [h, w] = S.man.shape, W = $("stage").width;
  S.selCand = k; S.zoom = 4;
  const s = (W / w) * S.zoom;
  S.panX = -((c.x + 0.5) - w / 2) * s; S.panY = -((h - 1 - c.y + 0.5) - h / 2) * s;
  candPanel(); draw();
}

// ---------- spectrum on click ----------
const VCOL = ["#7cc4ff", "#f5c26b", "#9be39b", "#ff8ad8", "#c9a3ff", "#ff9e7a", "#7fe0d9", "#e8e88a"];
const BCOL = { D1: "#8fb8ff", D2: "#7fe0d9", D3: "#9be39b", D4: "#e8e88a", D5: "#f5c26b", D6: "#ff9e7a" };
async function clickSpectrum(e) {
  const cv = $("stage"), k = cv.width / cv.clientWidth, X = e.offsetX * k, Y = e.offsetY * k;
  const [h, w] = S.man.shape, W = cv.width, H = cv.height, s = (W / w) * S.zoom;
  const gx = (X - (W / 2 - (w / 2) * s + S.panX)) / s - 0.5;
  const gy = h - 1 - ((Y - (H / 2 - (h / 2) * s + S.panY)) / s - 0.5);
  if (gx < 0 || gy < 0 || gx > w - 1 || gy > h - 1) return;
  $("spectext").textContent = "Measuring every exposure at this position…";
  try {
    let sp;
    if (S.mode === "static") {
      const list = S.man.spectra || [];
      let best = null;
      for (const q of list) { const d = Math.hypot(q.x - gx, q.y - gy); if (d < 5 && (!best || d < best[0])) best = [d, q]; }
      if (!best) { $("spectext").textContent = "The static showcase has spectra for the field centre and the marked candidates. Click one of those, or run the local server to measure any position."; return; }
      sp = best[1];
    } else {
      const name = S.base.replace(/\/$/, "").split("/").pop();
      sp = await getJSON(`api/spectrum?base=${encodeURIComponent(name)}&x=${gx.toFixed(2)}&y=${gy.toFixed(2)}`);
    }
    S.specXY = [sp.x ?? gx, sp.y ?? gy]; draw();
    showSpectrum(sp);
  } catch (err) { $("spectext").textContent = "Spectrum failed: " + (err.message || err); }
}
function axes(c, W, H, pad, x0, x1, y0, y1, xl, yl, xt) {
  c.fillStyle = "#0e1118"; c.fillRect(0, 0, W, H);
  c.strokeStyle = "#39404f"; c.lineWidth = 1; c.strokeRect(pad.l, pad.t, W - pad.l - pad.r, H - pad.t - pad.b);
  c.fillStyle = "#9aa3b5"; c.font = "11px system-ui";
  const X = (v) => pad.l + ((v - x0) / (x1 - x0)) * (W - pad.l - pad.r);
  const Y = (v) => H - pad.b - ((v - y0) / (y1 - y0)) * (H - pad.t - pad.b);
  for (const t of xt) { c.fillText(t.l, X(t.v) - 8, H - pad.b + 13); }
  for (let i = 0; i <= 4; i++) { const v = y0 + (i / 4) * (y1 - y0); c.fillText(v.toPrecision(3), 2, Y(v) + 4); }
  c.fillText(xl, W / 2 - 40, H - 3); c.save(); c.translate(11, pad.t + 60); c.rotate(-Math.PI / 2); c.restore();
  c.fillText(yl, pad.l + 4, pad.t + 11);
  return [X, Y];
}
function yRange(vals) {
  const v = vals.filter(Number.isFinite).sort((a, b) => a - b);
  if (!v.length) return [0, 1];
  let lo = v[Math.floor(0.02 * (v.length - 1))], hi = v[Math.ceil(0.98 * (v.length - 1))];
  const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.2 || 1;
  return [Math.min(0, lo - pad), hi + pad];
}
function showSpectrum(sp) {
  const pts = sp.points.filter((p) => p.wav), visits = [...new Set(pts.map((p) => p.visit))].sort((a, b) => a - b);
  $("spectext").innerHTML = `${pts.length} exposures measured at RA ${sp.ra.toFixed(5)}°, Dec ${sp.dec.toFixed(5)}°` +
    `${sp.moving ? " — <b>following the source's measured motion</b>" : ""}${sp.snapped ? ` (snapped to: ${sp.snapped})` : ""}. ` +
    `Units µJy. Colours = visits; grey hollow = flagged pixels in the aperture. ${sp.note || ""}`;
  const cv = $("specplot"), c = cv.getContext("2d"); cv.hidden = false;
  const good = pts.filter((p) => !p.flagged);
  const [y0, y1] = yRange(good.flatMap((p) => [p.flux - p.err, p.flux + p.err]));
  const pad = { l: 48, r: 10, t: 16, b: 30 };
  const [X, Y] = axes(c, cv.width, cv.height, pad, 0.7, 5.05, y0, y1, "wavelength (µm)", "flux density (µJy)",
    [1, 2, 3, 4, 5].map((v) => ({ v, l: String(v) })));
  for (const [v, lab] of [[3.0, "H₂O ice"], [3.3, "CH₄"], [4.27, "CO₂"], [4.67, "CO"]]) {
    c.strokeStyle = "rgba(255,255,255,.25)"; c.setLineDash([4, 4]); c.beginPath(); c.moveTo(X(v), pad.t); c.lineTo(X(v), cv.height - pad.b); c.stroke();
    c.setLineDash([]); c.fillStyle = "#cfd6e4"; c.fillText(lab, X(v) + 3, pad.t + 24 + (v === 3.3 ? 12 : 0));
  }
  if (y0 < 0) { c.strokeStyle = "#39404f"; c.beginPath(); c.moveTo(pad.l, Y(0)); c.lineTo(cv.width - pad.r, Y(0)); c.stroke(); }
  for (const p of pts) {
    const col = p.flagged ? "#777" : VCOL[visits.indexOf(p.visit) % VCOL.length];
    c.strokeStyle = col; c.fillStyle = col; c.lineWidth = 1;
    c.beginPath(); c.moveTo(X(p.wav), Y(p.flux - p.err)); c.lineTo(X(p.wav), Y(p.flux + p.err)); c.stroke();
    c.beginPath(); c.arc(X(p.wav), Y(p.flux), 2.6, 0, 2 * Math.PI); p.flagged ? c.stroke() : c.fill();
  }
  visits.forEach((v, i) => { const q = pts.find((p) => p.visit === v); c.fillStyle = VCOL[i % VCOL.length]; c.fillText(`visit ${i + 1}: ${q.time.slice(0, 10)}`, cv.width - pad.r - 130, pad.t + 12 + 13 * i); });
  // light curve
  const lc = sp.lightcurve || [], lv = $("lcplot"), d = lv.getContext("2d"); lv.hidden = !lc.length;
  if (!lc.length) return;
  const m0 = Math.min(...lc.map((q) => q.mjd)) - 10, m1 = Math.max(...lc.map((q) => q.mjd)) + 10;
  const [l0, l1] = yRange(lc.flatMap((q) => [q.flux - q.err, q.flux + q.err]));
  const ticks = []; for (let t = Math.ceil(m0 / 60) * 60; t <= m1; t += 60) ticks.push({ v: t, l: new Date((t - 40587) * 864e5).toISOString().slice(2, 7) });
  const [LX, LY] = axes(d, lv.width, lv.height, { l: 48, r: 10, t: 16, b: 30 }, m0, m1, l0, l1, "date (per-visit mean of unflagged exposures)", "µJy", ticks);
  for (const b of [...new Set(lc.map((q) => q.band))]) {
    const q = lc.filter((x) => x.band === b).sort((x, y) => x.mjd - y.mjd);
    d.strokeStyle = BCOL[b] || "#ccc"; d.fillStyle = d.strokeStyle; d.beginPath();
    q.forEach((x, i) => (i ? d.lineTo(LX(x.mjd), LY(x.flux)) : d.moveTo(LX(x.mjd), LY(x.flux)))); d.stroke();
    for (const x of q) { d.beginPath(); d.moveTo(LX(x.mjd), LY(x.flux - x.err)); d.lineTo(LX(x.mjd), LY(x.flux + x.err)); d.stroke(); d.beginPath(); d.arc(LX(x.mjd), LY(x.flux), 3, 0, 2 * Math.PI); d.fill(); }
    const last = q[q.length - 1]; d.fillText(b, LX(last.mjd) + 5, LY(last.flux) + 4);
  }
}

function wl(w) { return !w ? "λ n/a" : Array.isArray(w) ? (w[0] === w[1] ? `${w[0].toFixed(3)} µm` : `${w[0].toFixed(3)}–${w[1].toFixed(3)} µm`) : `${w.toFixed(3)} µm`; }
function label() {
  const m = S.meta[S.i] || {}, n = S.frames.length;
  let t;
  if (m.kind === "visit") t = `${S.band} · visit ${S.i + 1}/${n} · ${m.time.slice(0, 10)} · +${m.days} d · ${wl(m.wav)} · ${m.n} exp`;
  else if (m.kind === "exposure") t = `${S.band} · exposure ${S.i + 1}/${n} · ${m.time} · +${m.days} d · ${wl(m.wav)}`;
  else if (m.kind === "all") t = `${S.band} · all ${m.n} exposures stacked · ${wl(m.wav)}`;
  else if (m.kind === "diff1") t = `${S.band} · Subtract needs at least two visits; this detector has one so far.`;
  else t = `${S.band} · visit ${S.subA + 1} (${m.a.time.slice(0, 10)}) − visit ${S.subB + 1} (${m.b.time.slice(0, 10)}) · +${(m.a.mjd - m.b.mjd).toFixed(0)} d · white = new, black = gone`;
  $("label").textContent = t;
}

function metaPanel() {
  const m = S.meta[S.i] || {}, M = S.man, rows = [];
  const add = (k, v) => rows.push(`<tr><td>${k}</td><td>${v}</td></tr>`);
  add("Field", `RA ${M.ra.toFixed(5)}°, Dec ${M.dec.toFixed(5)}°, ${M.fov}′ (${M.scale_arcsec.toFixed(1)}″/px)`);
  add("Data path", `${M.source || "?"}; ${M.n_found} exposures found, ${M.n_failed} downloads failed; built ${M.built}`);
  if (S.cov) add("Background scan", S.cov.periods_total ? `${S.cov.state}: ${S.cov.periods_done}/${S.cov.periods_total} candidate periods searched, ${S.cov.found} exposures so far (reload to pick up more)` : S.cov.state);
  if (m.kind === "visit") {
    add("Visit time", `${m.span[0]} → ${m.span[1]} UTC (${m.n} exposures)`);
    add("Wavelength", wl(m.wav)); add("Release / pipeline", `${m.releases.join(", ")} / ${m.versions.join(", ")}`);
    add("Flagged pixels", `${m.flag_pct}% any flag; ${m.masked_pct}% masked`);
    add("Flag bits present", m.flag_bits.join(", ") || "none");
    add("Observation IDs", `<span class="ids">${m.obsids.join(" ")}</span>`);
  } else if (m.kind === "exposure") {
    add("Time", `${m.time} UTC (MJD ${m.mjd})`);
    add("Wavelength", `${wl(m.wav)}${m.bw ? ` (band width ${m.bw.toFixed(3)} µm)` : ""}`);
    add("Release / pipeline", `${m.release} / ${m.version}`);
    add("Flagged pixels", `${m.flag_pct}% any flag; ${m.masked_pct}% masked`);
    add("Flag bits present", m.flag_bits.join(", ") || "none");
    add("Observation ID", `<span class="ids">${m.obsid}<br>${m.planeid}</span>`);
  } else if (m.kind === "all") {
    add("Span", `${m.span[0]} → ${m.span[1]} UTC`); add("Wavelength", wl(m.wav));
  } else if (m.kind === "diff") {
    add("A", `${m.a.time} UTC, ${wl(m.a.wav)}`); add("B", `${m.b.time} UTC, ${wl(m.b.wav)}`);
    add("Reading it", "A mover shows as a white/black pair. Same-spot changes are variability, or a wavelength difference between the visits.");
  }
  add("Masking", "IRSA photometry mask (HOT, COLD, NONFUNC, PERSIST, …). SOURCE is not masked.");
  $("meta").innerHTML = `<table>${rows.join("")}</table>`;
}

// ---------- playback & UI ----------
function delay() { return 1400 / (+$("speed").value || 3); }
function play() { if (S.frames.length < 2) return; S.playing = true; $("play").textContent = "❚❚"; tick(); }
function tick() { clearTimeout(S.timer); S.timer = setTimeout(() => { if (!S.playing) return; step(1); tick(); }, delay()); }
function stop() { S.playing = false; clearTimeout(S.timer); $("play").textContent = "▶"; }
function step(d) { const n = S.frames.length; if (!n) return; S.i = (S.i + d + n) % n; draw(); }
function zoom(f) { S.zoom = Math.max(1, Math.min(12, S.zoom * f)); if (S.zoom === 1) S.panX = S.panY = 0; draw(); }

function syncURL() {
  const p = new URLSearchParams({ ra: String($("ra").value).trim(), dec: String($("dec").value).trim(), fov: $("fov").value, mode: S.view, band: S.band });
  if (document.body.classList.contains("embed")) p.set("embed", "1");
  history.replaceState(null, "", `?${p}`);
}

function bindUI() {
  $("form").onsubmit = (e) => { e.preventDefault(); load(); };
  $("fov").oninput = () => { $("fovwarn").hidden = +$("fov").value <= 10; };
  $("band").onchange = () => { S.band = $("band").value; S.i = 0; setView(); };
  $("mode").onchange = () => { S.view = $("mode").value; S.i = 0; setView(); };
  $("visitsel").onchange = () => { S.visitSel = +$("visitsel").value; S.i = 0; setView(); };
  $("suba").onchange = () => { S.subA = +$("suba").value; setView(); };
  $("subb").onchange = () => { S.subB = +$("subb").value; setView(); };
  $("play").onclick = () => (S.playing ? stop() : play());
  $("prev").onclick = () => { stop(); step(-1); };
  $("next").onclick = () => { stop(); step(1); };
  $("scrub").oninput = () => { stop(); S.i = +$("scrub").value; draw(); };
  $("speed").oninput = () => S.playing && tick();
  $("zin").onclick = () => zoom(1.5); $("zout").onclick = () => zoom(1 / 1.5);
  $("cross").onchange = draw; $("marks").onchange = draw;
  $("embedbtn").onclick = () => {
    const u = new URL(location.href); u.searchParams.set("embed", "1");
    const ta = $("embedcode");
    ta.value = `<iframe src="${u.href}" width="480" height="520" style="border:0" loading="lazy" title="SkyDrift blink"></iframe>`;
    ta.hidden = false; ta.select();
  };
  $("linkbtn").onclick = () => navigator.clipboard && navigator.clipboard.writeText(location.href);
  document.addEventListener("keydown", (e) => {
    if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName) || $("viewer").hidden) return;
    if (e.key === "ArrowRight") { stop(); step(1); e.preventDefault(); }
    else if (e.key === "ArrowLeft") { stop(); step(-1); e.preventDefault(); }
    else if (e.key === " ") { S.playing ? stop() : play(); e.preventDefault(); }
    else if (e.key === "+" || e.key === "=") zoom(1.5);
    else if (e.key === "-") zoom(1 / 1.5);
  });
  const cv = $("stage");
  cv.addEventListener("wheel", (e) => { e.preventDefault(); zoom(e.deltaY < 0 ? 1.25 : 0.8); }, { passive: false });
  let drag = null;
  cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, px: S.panX, py: S.panY }; cv.setPointerCapture(e.pointerId); });
  cv.addEventListener("pointermove", (e) => {
    if (!drag || S.zoom === 1) return;
    const k = cv.width / cv.clientWidth;
    S.panX = drag.px + (e.clientX - drag.x) * k; S.panY = drag.py + (e.clientY - drag.y) * k; draw();
  });
  cv.addEventListener("pointerup", (e) => {
    const moved = drag ? Math.hypot(e.clientX - drag.x, e.clientY - drag.y) : 99;
    drag = null;
    if (moved < 5) clickSpectrum(e);
  });
}

init();
