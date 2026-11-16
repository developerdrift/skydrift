// AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
// Headless regression check of the static showcase: runs the real app.js against a stub DOM and
// a static web server serving docs/, clicks every preset, and renders every detector x mode.
// Usage: node scripts/check_static.js docs/static/app.js http://127.0.0.1:8765/
// Prints one line per preset and exits 1 if any preset errors or has no multi-frame blink.
const fs = require("fs");
const BASE = process.argv[3];
const els = {};
function el(id) {
  if (!els[id]) els[id] = {
    id, value: "", hidden: false, disabled: false, textContent: "", innerHTML: "", children: [], dataset: {},
    style: {}, checked: id === "cross" || id === "marks", width: 600, height: 600, clientWidth: 600, max: 0,
    querySelectorAll: () => [], classList: { add() {}, remove() {}, toggle() {} },
    appendChild(c) { this.children.push(c); }, addEventListener() {}, setPointerCapture() {}, select() {},
    getContext: () => ({ createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
      putImageData() {}, drawImage() {}, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {},
      stroke() {}, fillText() {}, arc() {}, fill() {}, setLineDash() {}, save() {}, restore() {},
      translate() {}, rotate() {}, strokeRect() {} }),
  };
  return els[id];
}
global.document = { getElementById: el, createElement: () => el("tmp" + Math.random()),
  body: { classList: { add() {}, contains: () => false } }, addEventListener() {}, activeElement: { tagName: "BODY" } };
global.location = { search: "", href: BASE + "index.html" };
global.history = { replaceState() {} };
global.navigator = {};
const realFetch = fetch;
global.fetch = (u) => realFetch(new URL(u, BASE).href);
eval(fs.readFileSync(process.argv[2], "utf8") + ";globalThis.__a = {S, setView, stop, showErr, showSpectrum, clickSpectrum};");
const { S, setView, stop, showErr, showSpectrum, clickSpectrum } = globalThis.__a;
(async () => {
  await new Promise((r) => setTimeout(r, 1500));
  let fail = 0;
  if (S.mode !== "static" || S.presets.length !== 5) { console.log(`FAIL mode=${S.mode} presets=${S.presets.length}`); fail++; }
  const vl = el("vallink").href, vr = await fetch("validation.html");
  if (vl !== "validation.html" || !vr.ok) { console.log(`FAIL truth-check link href=${vl} status=${vr.status}`); fail++; }
  else console.log("PASS truth-check link -> validation.html (200)");
  console.log(`default view: preset=${S.presets[0].key} mode=${S.view} band=${S.band} loaded=${!!S.man}`);
  for (const b of el("presets").children) {
    showErr("");
    b.onclick();
    await new Promise((r) => setTimeout(r, 3000));
    let maxFrames = 0, renders = 0, cands = 0;
    try {
      for (const band of Object.keys(S.man.bands)) {
        S.band = band;
        cands += (S.man.bands[band].candidates || []).length;
        for (const v of ["visits", "exposures", "add", "subtract"]) {
          S.view = v; await setView(); stop(); renders++;
          if (v === "visits" || v === "exposures") maxFrames = Math.max(maxFrames, S.frames.length);
        }
      }
      for (const sp of S.man.spectra || []) showSpectrum(sp);
      S.zoom = 1; S.panX = S.panY = 0; el("spectext").textContent = "";
      await clickSpectrum({ offsetX: 300, offsetY: 300 });   // click the image centre
      if (!/exposures measured/.test(el("spectext").innerHTML || el("spectext").textContent)) throw new Error("spectrum click: " + (el("spectext").textContent || el("spectext").innerHTML).slice(0, 80));
    } catch (e) { el("err").hidden = false; el("err").textContent = String(e); }
    const err = el("err").hidden ? "" : el("err").textContent;
    const ok = !err && maxFrames >= 2;
    if (!ok) fail++;
    console.log(`${ok ? "PASS" : "FAIL"} ${b.dataset.key}: bands=${Object.keys(S.man.bands).length} renders=${renders} ` +
      `maxBlinkFrames=${maxFrames} candidates=${cands} spectra=${(S.man.spectra || []).length} exposures=${S.man.n_found}${err ? " error=" + err : ""}`);
  }
  console.log(fail ? `STATIC CHECK FAILED (${fail})` : "STATIC CHECK OK");
  process.exit(fail ? 1 : 0);
})();
