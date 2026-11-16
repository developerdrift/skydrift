# PROGRESS

<!-- STATE -->
## STATE (Session 1, updated 2026-11-15 18:06 US Central). Tags: v1, v2

**Running in the background (never wait on these):**
- `scripts/coverage_daemon.py --until 21:30 --truth`: S3 header scan for the 5 presets, the 36
  truth-check stars and app-queued positions. Log: `cache/coverage/daemon.log`.
- `scripts/refresh_loop.py --every 30 --until 21:30`: each cycle runs `scripts/refresh.py`, which
  (1) rebuilds stale preset views and their candidates, (2) re-runs the truth check,
  (3) exports `docs/`, (4) regenerates `demo/`. Log: `cache/refresh_loop.log`,
  status `cache/refresh_status.json`.
- At 21:30 it runs a final refresh, then the regression check (pytest, all 5 presets in `docs/`
  via `scripts/check_static.js`, the validation page) and writes `cache/final_check.json`.
- **Then (owner: whoever is active):**
  1. Fix anything broken.
  2. Commit the final snapshot; do not change features after that.
  3. Fill "Final numbers" below and in `SUBMISSION.md`.

**Phase 3A (done):** `engine/candidates.py`; markers and a ranked list in the app.
- WISE 0855 D6 motion recovered: 4.07" vs 4.61" predicted with parallax, PA 281 vs 277.
- RW Aur flagged variable: x1.73 at overlapping wavelengths, 8.5 sigma.
- A neighbour near WISE 0855 in D3 is correctly rejected.

**Phase 3C (done, numbers still growing):** `scripts/truth_check.py`, `/validation` page, plot in
the README.
- At 18:05: 16 measurements of 11 stars, 10 consistent. RMS vector residual 1.19" for the
  consistent ones, 2.63" for all (outliers kept).
- The unsaturated and saturated-core tiers are reported separately.
- Comparison values are literature values from memory (no live Gaia).
- Below the spec's 20-40 stars so far; the daemon is still adding truth-star visits.

**Phase 3B (done, 19:37):** spectrum on click. Live: click anywhere (`/api/spectrum`, ~6 s).
Static: precomputed for the field centre and each distinct candidate; all 5 presets render in
`check_static.js`. On real WISE 0855 data: 74 exposures; D6 ~550 uJy. The 12" aperture also
contains a background star ~9" away, so the 1-2 um points are dominated by that star.
**Phase 3D:** not built (scope).

**Truth check at 19:37 (automatic refresh, data still growing):** 35 measurements of 24 stars,
24 consistent within 3 sigma. RMS vector residual 0.98" (consistent) / 1.76" (all, outliers kept). Unsaturated tier only: 23 measurements of 16 stars, 17 consistent, RMS 0.98" / 1.54".
WISE 0855 D6 is unchanged: measured 4.07" vs predicted 4.61".

**Phase 4 (done except the final snapshot):**
- README: candidates, truth check, updating for new releases, network calls, credits, licenses.
- `AI_USAGE.md` ("Human decisions and testing" left empty).
- `docs/prompts/` (SPEC plus session 1 prompts).
- `demo/` (GIFs, MP4s, WISE D1-vs-D6 panel, `storyboard.md`, `subtitles.srt`).
- `SUBMISSION.md` drafts (with numbers marked "final").
- **TODO:** IRSA's dataset DOI for SPHEREx (not found on reachable pages; not invented).

### Final numbers (snapshot 2026-11-15; daemon + refresh stopped 21:31, final refresh finished 21:47)
- **Exposures per preset** (PARTIAL coverage: sampled S3 header scan, not a complete survey):
  - Barnard's Star 74 (D1 3 visits, D4 3)
  - Epsilon Indi B 42 (D1, D2, D4, D5: 2 visits each)
  - WISE 0855-0714 98 (D1, D2, D4, D5: 3 visits; D3, D6: 2)
  - RW Aurigae 92 (D1 3 visits, D4 3)
  - R Draconis 292 (D1, D3, D6: 3 visits)
- **Truth check** (literature PM/parallax quoted from memory, NOT live Gaia DR3):
  - 39 stars tried; 48 measurements of 29 stars; 35 consistent within 3 sigma.
  - RMS vector residual: 1.86" over all (outliers kept), 0.85" for the consistent measurements.
  - Unsaturated tier only: 32 measurements of 18 stars, 25 consistent; RMS 1.38" over all,
    0.81" for the consistent ones.
- **WISE 0855-0714 D6:** measured 4.07" vs predicted 4.61" (PM + parallax), PA 281 vs 277.
  - D3 and D5 do not match the prediction: D3 is a background neighbour; D5 measured 5.36" vs 8.28".
- **Epsilon Indi B:** D1 2.25" vs 2.67"; D4 3.87" vs 2.79"; all four detectors consistent within 3 sigma.
- **RW Aurigae:** variable in D1, flux x1.66 relative to the field (8.4 sigma, overlapping wavelengths).
- **Final regression (21:47):** pytest 19 passed; static docs/ check OK for all 5 presets (incl.
  spectrum click and Truth-check link); validation page assets 200.

**Phase 1 acceptance (done, 17:15).** Files: `phase1_out/barnard_visit_blink_D1_display_saturated.gif`
(+ `_zoom.gif`, `barnard_phase1_display_saturated.json`).
- Barnard's Star is SATURATED: BLOOM, SUR_ERROR, OVERFLOW and TRANSIENT are set on its core, and
  the official mask hides it.
- The GIF keeps those pixels for DISPLAY ONLY (`--display-saturated`).
- D1 visits 2025-09-09 (7 exp) and 2026-03-11 (1 exp). Measured shift 6.52" vs predicted 5.22"
  (saturated profile, approximate). Neighbours moved a median of 0.41" (n=3).
- A fainter high-PM star would be a cleaner test (Phase 3C).

**Phase 2 acceptance (done).** All 5 presets load through the live server: 3-19 s cold, 0.1 s warm.
Every preset has >= 2 visits in D1.

**Phase 2S / v1 (done).** `docs/` export is 7.9 MB. All 5 presets x all detectors x 4 modes were
checked headlessly through the real app.js on a local static server. Tagged `v1`.

Coverage at tag time was PARTIAL (the daemon is still scanning): Barnard 26 exposures, Eps Indi B 22,
WISE 0855 36, RW Aur 16, R Dra 69. Re-run `export_showcase.py` after the daemon finishes to refresh
`docs/`.

**Not done / next:**
- Re-export `docs/` once the daemon run (ends ~17:55) has added visits; commit.
- Phase 3 (candidates, truth check, spectra, context) has not started.
- Positions and PMs in `engine/targets.py` are unverified literature values; replace them from
  Gaia DR3 when TAP is back.

## Older state notes (Session 1, ~14:00)

### !! Correction (~16:40): the Phase 0 coverage below came from a buggy S3 listing !!
Each S3 period holds a main dir `l2b-v27-...` (~1800 files/detector) and a small `l2b_retry-v27-...` dir
(~7 files). The old code listed only the dir that sorted last, which was the retry dir, so most periods
looked nearly empty. The 24-exposure WISE 0855 set is therefore a small subset of the real coverage.
Fixed in `engine/s3scan.py` (all version dirs are merged). Phase 0 numbers below are kept for history.
Also measured: consecutive sequences jump ~28 deg (one orbit is ~13 sequences), exposures within a
sequence step ~0.2 deg, and pointings are 82-127 deg from the Sun.

### Phase 0 result (S3 fallback, ~15:10). REAL DR1 data.
**PARTIAL coverage from sparse header sampling - full scan not yet run.** This is NOT a complete survey.
- Script: `probe_s3.py`. Outputs in `probe_out/`:
  - `exposures_s3.csv`: per exposure, wavelength at target, flag fraction, target pixel flag value.
  - `probe_s3_results.json`.
  - `w0855_d6_contact.png`, `w0855_stacks_D1-D6.png`.
- **Counts:** 24 exposures. D1, D2, D4, D5: 4 each in visit 0. D3, D6: 4 each in visit 1.
- **Visits** (30-day gap): visit 0 = 2025-05-06 (D1, D2, D4, D5); visit 1 = 2026-04-23 (D3, D6).
  Each band has only one visit in this set.
- **Wavelength at target (um):** D1 0.993-1.066, D2 1.280-1.373, D3 1.878-2.011, D4 3.358-3.638,
  D5 4.039-4.145, D6 4.617-4.719. Each exposure sees a different wavelength, as expected.
- **Position:** the reference epoch is unverified, because CatWISE (IRSA TAP) and SIMBAD were both
  unreachable. Two hypotheses were tested: A = challenge coords at 2010.5, B = at J2000.
  PM (-8.118, +0.680)"/yr from Luhman & Esplin 2016, quoted from memory.
- **FLAGS (known limitation, revisit when IRSA docs are back):** no bit names in any header, so
  ANY nonzero flag is masked and no bit meanings are assumed. That masks **47% of pixels** on average.
  - Observed per-bit pixel fractions: bit21 = 44%, bit19 = 1.6%, bit28 = 1.4%, bit0 = 0.6%,
    bits 2 and 6 = 0.4%, bit17 = 0.1%.
  - At the target pixel: bit21 is set in 24/24 exposures (hypothesis A) and 18/24 (hypothesis B).
- **Detected in stacked D6? NO, it can't be assessed.** With any-nonzero masking the target position
  is masked in every D6 exposure, so stack coverage there is 0 and S/N is undefined for both A and B.
  This is a masking outcome, not evidence that the source is absent.
- **DIAGNOSTIC run** (`probe_s3.py --unmask-bit 21`; files suffixed `_diag_unmask_bit21`;
  originals untouched):
  > DIAGNOSTIC - bit 21 unmasked because it is set in 100% of exposures at this position and covers
  > ~44% of all pixels uniformly, which is inconsistent with it marking a real per-pixel defect.
  > Meaning not confirmed - treat this detection result as provisional.
  - (The spatial uniformity of bit 21 was not separately checked; the 44% is a mean over files.)
  - **Stacked D6 (n=4, 2026-04-23): S/N 7.9 at hypothesis A, 0.2" from prediction -> DETECTED
    (provisional).** Hypothesis B: S/N -0.4, not detected. A faint source is visible at A in each
    of the 4 single exposures in `w0855_d6_contact_diag_unmask_bit21.png`.
  - Other bands at A: D1 2.2, D2 4.8, D3 3.8, D4 1.5, D5 3.5, all with peaks 2-5" off.
    No other band reaches 5.
  - Cautions:
    - Only one D6 visit, so motion cannot confirm identity; the source could be an unrelated object.
    - D2 at 4.8 is unexpected for a Y dwarf at 1.3 um. Its peak is 5" off, near the edge of the
      search radius, so it may be a neighbour or a sign that the noise model underestimates noise.
    - Hypothesis A (challenge coords at ~2010.5) is favoured by this data but not independently verified.
- Photometry method in `probe_s3.py`: 9.3" radius aperture with a peak search within 6.2"; noise comes
  from the same procedure at 400 random positions (sigma-clipped).

### Phase 0 history: IRSA query outage
- IRSA TAP and SIA return HTTP 502 (or hang) for every query, even `SELECT TOP 1`.
  Last success was ~11:58 (schema queries). Main IRSA site still answers.
- Retries of the Phase 0 TAP query (D6 at WISE 0855): **5 attempts, all failed**.
  1. 12:54 502 after ~25 min hang (no client timeout; bug since fixed).
  2. ~12:58 hung >30 min, killed.
  3. 13:32 read timeout (90 s).
  4. 13:37 read timeout (90 s).
  5. 13:41 502.
  The loop was stopped there. Earlier ad-hoc checks 12:06-12:25 also failed.
- No WISE 0855 counts, visit dates, wavelengths or detection result exist yet.
- `probe.py` is written (CatWISE PM lookup -> all-detector query -> dedupe -> visits ->
  cached cutouts -> wavelength per exposure -> D6 contact sheet -> co-moving D1-D6 stacks ->
  detected yes/no). **Never run against real data.**

### S3 fallback (tested ~14:20, REAL data, anonymous HTTPS, no new packages)
- `https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/` works: list returns 200 and ranged GETs return 206.
  Top level has `dr1/ qr2/ qr3/`. Layout:
  `dr1/level2/<period>/l2b-v27-<procdate>/<det 1-6>/level2_<period>_<seq>_<n>D<det>_spx_l2b-v27-<procdate>.fits`.
- 110 DR1 planning periods (2025W17_4B .. 2026W20_1A), ~1563 files per detector per period,
  so about 1M files in DR1. Each file is a full 2040x2040 frame, ~66 MB, uncompressed.
  There's **no cutout service and no spatial index**.
- A ranged read of the first 57.6 KB gives the primary header and the IMAGE header.
  - **Verified:** VERSION=7.0.5; BUNIT=MJy/sr; RA---TAN-SIP; pixel scale 6.17"/px.
  - **Verified:** time is in MJD-OBS / MJD-AVG.
  - **Verified:** spectral WCS is CTYPE1W='WAVE-TAB' with PS1_0W='WCS-WAVE', matching assumption 3.
- Coverage search would need sampled header scans; a cutout would need byte-range reads of the
  rows around the target in IMAGE, FLAGS, VARIANCE and ZODI (~1 MB per exposure).
- Approved treating the S3 bucket as IRSA data.
- **Service check (~14:30):** TAP, SIA2 and SCS all 502; Data Explorer backend 500.
  **The cutout service works:** `https://irsa.ipac.caltech.edu/ibe/data/spherex/<S3 key>?center=RA,DECd&size=DEG`
  (the S3 key includes the `dr1/` prefix).
- **WISE 0855 coverage via S3 header scan** (`scripts/find_exposures_s3.py`, `engine/s3scan.py`;
  4 runs, ~14 min total of a 30 min cap). It found **24 exposures** (sampled scan, so it may be incomplete):
  - 2025W19_1B (2025-05-06): D1, D2, D4, D5, 4 each.
  - 2026W17_1B (2026-04-23): D3, D6, 4 each.
  - So **D6 has only 4 exposures, all in one visit.** No D6 multi-visit blink is possible from this set.
  - Nothing found for Nov 2025.
  - Run 1 found 0 (too sparse). Run 2 found 16 but missed D3/D6, because their centres are 7.7 deg
    from D1's and the cutoff was 7 deg.
  - The result list is in `cache/s3index/wise0855_covering.json`. The header cache is reusable for other targets.
- **One real D6 cutout checked** (0.05 deg -> 29x29 px):
  - HDUs PRIMARY, IMAGE, FLAGS, VARIANCE, ZODI, EPSF, WCS-WAVE, as expected.
  - Wavelength at target 4.617 um (bandwidth 0.036 um) via the -TAB spectral WCS. The engine's
    wavelength_at() works on real data.
  - **FLAGS header has NO MP_* bit names.** The engine therefore masks all flags, which is 30% of
    pixels (bits 0, 2, 6, 17, 19, 21, 28). Bit meanings are needed before masking is sensible.

### Schema verified from real TAP (before the outage)
- `spherex.plane`: `obsid, planeid, datarelease, metarelease, energy_bandpassname,
  time_bounds_lower[d], energy_bounds_lower/upper[m], poly, pt, provenance_version, ...`
- `spherex.artifact`: `planeid, uri, producttype, releasetype, contentlength, ...`
- Also present: `gaia_dr3_source`, `catwise_2020`.

### Phase 1 engine: CODE WRITTEN, TESTED ON SYNTHETIC DATA ONLY
- `engine/fetch.py` TAP query (hard timeout and backoff), dedupe that prefers DR1, 30-day visit
  clustering, parallel cutouts (max 10 workers), cache `cache/<ra>_<dec>_<size>/<release>/<planeid>.fits`
  plus `query.ecsv` as an offline fallback.
- `engine/calibrate.py` IMAGE minus ZODI, masks hard flag bits by MP_* name, sigma-clipped
  median removed, wavelength from the spectral WCS (key W) at the target.
- `engine/regrid.py` (not reproject.py, to avoid shadowing the package): north-up TAN grid,
  3.1"/px, `reproject_interp`.
- `engine/stack.py` inverse-variance stacks per (visit, band), plus an all-epoch stack.
- `engine/render.py` one shared asinh stretch, GIF with labels and crosshair.
- `engine/pipeline.py` glue: `run_target(ra, dec, fov_arcmin, root)`.
- `engine/measure.py` windowed centroid.
- **SYNTHETIC test data** (`tests/synthetic.py`): made-up cutouts with the SPEC HDU layout
  and `VERSION="SYNTHETIC"`. 12 static stars plus one mover at 10"/yr, 4 visits x 3 exposures,
  hot pixels, ZODI gradient, wavelength varying per exposure.
  `pytest`: 10/10 pass (clustering, URL, dedupe, cache reuse, -TAB wavelength lookup,
  flag masking, IVW maths, mover shift recovered within 2", static stars fixed within 0.7 px).
  `synthetic_out/SYNTHETIC_visit_blink_D6.gif` is a logic check, **not the Phase 1 acceptance GIF**.
- These synthetic results prove the code logic only. They say nothing about SPHEREx data or WISE 0855.

### Assumptions to RE-VERIFY on the first real cutout (before any further work)
1. `time_bounds_lower` is MJD.
2. `datarelease`/`metarelease` value formats (dedupe ranking is generic).
3. Spectral WCS really is an alternate `-TAB` WCS (key W) on the IMAGE header, using
   WCS-WAVE; check the CTYPE/PS/PV keys and that units come out in um.
4. FLAGS bit names are in the FLAGS header as MP_* keys (otherwise all flags get masked).
5. Pixel scale ~6.2"/px; IMAGE units (BUNIT); whether `uri` needs a leading-slash strip.
6. Whether variance survives bilinear regridding well enough for the IVW weights.

### Next step
1. Check TAP: `SELECT TOP 1 planeid FROM spherex.plane`.
2. When it's up: run `probe.py`, check assumptions 1-6 against its output, fix the engine,
   then rerun pytest.
3. Phase 1 acceptance: real visit-blink GIF of a high-PM star (Barnard's Star or a fainter
   Gaia high-PM star), then a background prefetch of all five targets.

### How to run
- `.venv/Scripts/python -m pytest` (offline; synthetic and unit tests)
- `.venv/Scripts/python scripts/synthetic_demo.py` (SYNTHETIC GIF)
- `.venv/Scripts/python probe.py` (needs IRSA)

### Cached targets: none. Git: not initialised at that point.
