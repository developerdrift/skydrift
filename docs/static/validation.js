// AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"use strict";
(async () => {
  const $ = (id) => document.getElementById(id);
  let d;
  try { d = await (await fetch(`static/validation/truth.json?t=${Date.now()}`)).json(); }
  catch { $("summary").textContent = "No truth-check results yet (run scripts/truth_check.py)."; return; }
  $("caveat").textContent = d.caveats.join(" ");
  const f = (v, n = 2) => (v == null ? "–" : (+v).toFixed(n));
  const u = d.unsaturated || {};
  $("summary").innerHTML = `<b>Unsaturated:</b> ${u.n_measurements ?? "–"} measurements of ${u.n_stars ?? "–"} stars,
    ${u.n_consistent ?? "–"} consistent; RMS vector residual <b>${f(u.rms_vector_residual_arcsec)}″</b>
    (${f(u.rms_vector_residual_consistent_arcsec)}″ for the consistent ones).<br>
    <b>All (incl. saturated cores):</b> <b>${d.n_measurements}</b> measurements of <b>${d.n_stars_measured}</b> stars
    (of ${d.n_stars} tried); <b>${d.n_consistent}</b> consistent with the prediction within 3σ.
    RMS vector residual: <b>${f(d.rms_vector_residual_arcsec)}″</b> over all, ${f(d.rms_vector_residual_consistent_arcsec)}″
    for the consistent ones (one SPHEREx pixel = 6.2″). Generated ${d.generated}.`;
  const rows = d.rows.map((r) => r.status === "measured"
    ? `<tr><td>${r.star}${r.saturated ? ' <span class="na">(saturated)</span>' : ""}</td><td>${r.band}</td><td>${f(r.baseline_days, 0)} d</td><td>${f(r.pred_shift)}″ @ ${f(r.pred_pa, 0)}°</td>
       <td>${f(r.meas_shift)}″ @ ${f(r.pa, 0)}°</td><td>${f(Math.hypot(...r.err_en) / Math.SQRT2)}″</td><td>${f(r.snr, 0)}</td>
       <td class="${r.matches_prediction ? "ok" : "no"}">${r.matches_prediction ? "yes" : "no"}</td></tr>`
    : `<tr><td>${r.star}</td><td>${r.band || "–"}</td><td colspan="6" class="na">${r.status}</td></tr>`);
  $("tbl").innerHTML = `<tr><th>Star</th><th>Det.</th><th>Baseline</th><th>Predicted</th><th>Measured</th>
    <th>±1σ</th><th>S/N</th><th>Consistent</th></tr>${rows.join("")}`;
})();
