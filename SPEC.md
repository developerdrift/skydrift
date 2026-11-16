# SkyDrift — build spec (NASA Space Apps 2026, "Planet X and SPHEREx")

Solo entry. Hard stop for all building: **Sunday Nov 15, 10:30 PM US Central**.
The build is split into 5 sessions. Each session prompt names the phases to do.

## Working rules (every session)

1. **Scope.** Do only the phases your session prompt names, in order, then stop.
   Do not refactor working code from earlier sessions.
2. **Handoff.** Sessions share no memory. Start by reading this file and PROGRESS.md.
   End by updating the `STATE` block at the top of PROGRESS.md: what works, what is
   broken, exact next step, how to run the app, which targets are cached.
3. **Always shippable.** Commit after every working step. Never leave main broken.
   Tag `v1` when the static showcase works, `v2` after Phase 3.
4. **Timebox.** If a feature is blocked for ~30 minutes, cut it, log why, move on.
5. **Efficiency.**
   - Progress updates: 10 lines max per update. No code dumps in chat.
   - Never print arrays, full FITS headers, or tables over 20 rows. Summarize.
   - Do not re-read files you just wrote. Do not re-download cached data.
   - Write scripts to files and run them. Avoid long inline one-off commands.
   - Develop against the smallest case first (one detector, 0.03 deg cutout).
   - Run long downloads in the background and keep working.
6. **Git identity.** Use the GitHub noreply identity provided before the first commit. Do not create a remote or push until told.
7. **Honesty.** Report real numbers even when they are mediocre. Never call a
   candidate a discovery. Never invent a result to pass an acceptance check.

## What we are building

A public web tool: enter RA/Dec, see SPHEREx images of that patch over time as a
short blink video, so anyone can spot moving or changing objects. Must be tested on
Barnard's Star, Epsilon Indi B, WISE 0855, RW Aurigae, R Draconis.
Judged on Impact, Creativity, Validity, Relevance, Presentation.

**The pitch:** it doesn't just show the sky changing. It tells you what changed,
how fast, and what it is made of, and it proves its measurements against known truth.

Three things set it apart:
- **Wavelength-fair blink.** SPHEREx sees each sky position at a different
  wavelength in every exposure. A naive blink flickers for that reason alone.
  We stack per visit and per detector so only real changes show.
- **Automatic candidates.** The tool finds movers and variables itself and
  measures them.
- **Truth check.** We recover known Gaia star motions with our own pipeline and
  publish the plot.

## Verified facts (from IRSA docs, use as-is)

- No keys or logins. Query with astroquery: `Irsa.query_tap(query)`.
- Tables: `spherex.artifact a JOIN spherex.plane p ON a.planeid = p.planeid`
  `WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), p.poly)`
  `AND p.energy_bandpassname = 'SPHEREx-D1'` ... `'SPHEREx-D6'`
  `ORDER BY p.time_bounds_lower` (observation time).
- Cutout URL: `'https://irsa.ipac.caltech.edu/' || a.uri || '?center=<ra>,<dec>d&size=<deg>'`
- Cutout file: HDU0 primary (has VERSION), then IMAGE, FLAGS, VARIANCE, ZODI, EPSF, WCS-WAVE.
- Wavelength at a pixel:
  ```python
  spatial_wcs = WCS(header); x, y = spatial_wcs.world_to_pixel(coord)
  spectral_wcs = WCS(header, fobj=hdulist, key="W"); spectral_wcs.sip = None
  wavelength, bandwidth = spectral_wcs.pixel_to_world(x, y)
  ```
- Parallel download: `ThreadPoolExecutor(max_workers=10)`, astropy `remote_timeout=120`,
  catch timeouts and HTTP errors, drop failed rows. Never exceed 10 workers. Retry with backoff.
- Current releases are DR1 and QR3 (QR2 is superseded). Wide and Deep survey data both exist.

## Verify with real data before relying on it

- Print the columns of `spherex.plane` and `spherex.artifact`. Find how to tell
  release and survey apart. Dedupe if an exposure appears twice (prefer DR1).
- Time units of `time_bounds_lower`. Histogram observation times for one target and
  define "visits" = clusters separated by gaps over 30 days.
- Pixel scale (expect about 6.2 arcsec/px), image units, FLAGS bit meanings.
- Confirm the wavelength-per-exposure behavior from the data.
- Motion is pixel-scale: Barnard's Star ~10.4"/yr, WISE 0855 ~8.1"/yr, Eps Indi ~4.7"/yr.
  Expect about 1 px shift per visit. Oversample, centroid, and difference.
- **WISE 0855 trap.** The challenge coordinates (08h55m10.831s -07d14m42.53s) are an
  old epoch. With about -8.1"/yr in RA and +0.7"/yr in Dec it has likely drifted
  1.5 to 2.5 arcmin west. Verify the epoch and proper motion, then propagate.
  Expect it only in D6 (maybe D5) and absent in D1 to D4. That contrast is a demo moment.
  If it is not detectable after one honest attempt, log it and move on.
- Approximate J2000 positions. Verify each and propagate to the observation epoch
  with Gaia DR3 proper motions (try IRSA TAP table `gaia_dr3_source`, confirm the name):
  - Barnard's Star 17h57m48.5s +04d41m36s
  - Eps Indi A 22h03m21.7s -56d47m10s (the B brown-dwarf pair is ~400" away, find it)
  - RW Aur 05h07m49.5s +30d24m05s
  - R Dra 16h32m40.2s +66d45m18s (high ecliptic latitude, expect many more epochs)
- Barnard's Star may be saturated. Check FLAGS. If centroids fail, say so and use
  fainter high-proper-motion stars for validation.

## Phase 0 — data proof (no UI)

`probe.py` for WISE 0855: exposures per detector, visit dates, wavelength at the
target per exposure, a contact-sheet PNG of D6 cutouts.
**Accept:** PROGRESS.md has the counts, visit dates, wavelength ranges, and a
yes/no on whether WISE 0855 is detected in a stacked D6 image.

## Phase 1 — engine (`engine/`)

- **fetch:** TAP query, parallel cutouts, disk cache keyed by (ra, dec, size, release).
  No hardcoded dates. Re-running picks up new releases automatically.
- **calibrate:** subtract ZODI, mask flagged pixels, remove residual median background.
- **reproject:** common north-up grid centered on the target, 2x oversampled (~3"/px),
  using the `reproject` package.
- **stack:** inverse-variance weighted per (visit, detector). Also an all-epoch stack.
- **render:** one shared asinh stretch for all frames in a sequence.

**Accept:** a GIF of a high-proper-motion star visibly shifting between visit stacks
while neighbors stay fixed.
**Then:** start a background job that pre-fetches and caches all five test targets.

## Phase 2 — app (FastAPI + plain HTML/JS, no build step)

- Inputs: RA/Dec in degrees or sexagesimal, field of view 2 to 30 arcmin (warn that
  bigger is slower), detector picker, mode picker. Progress bar while loading.
- Blink player: play/pause, speed, scrub bar, arrow keys, crosshair, zoom. Label
  shows date, days since first frame, and wavelength.
- Modes:
  1. Visit blink (per-detector stacks). Default.
  2. Exposure blink (single exposures inside one visit, wavelength shown).
  3. Add (stack everything).
  4. Subtract (frame A minus B, default last minus first).
- Every setting lives in the URL (`?ra=&dec=&fov=&mode=&band=`) and auto-loads.
  `&embed=1` hides the chrome for iframes. An "Embed this view" button gives the snippet.
- Metadata panel per frame: observation IDs, times, wavelength, release version,
  percent of flagged pixels and which flag bits.
- Preset buttons for the five test targets.
- A 3-step "how to spot a mover" intro in plain language.
- Look: dark, clean, readable on a phone. No frameworks.

**Accept:** all five presets load and blink from a warm cache.

## Phase 2S — static showcase (the public link judges click)

- `export_showcase.py` writes a static site into `docs/` with pre-rendered frames
  and metadata for the five presets. The same frontend runs with no backend
  (GitHub Pages).
- Minimal README: what it is, how to run, data credits.

**Accept:** opening `docs/index.html` through a local static server blinks all five
presets. Tag `v1`. **From here on the project is submittable.**

## Phase 3 — differentiators (in this order)

**A. Candidates.** Per visit, extract sources (`sep`, photutils fallback) from a
detection stack. Match across visits. Remove the field's median offset. Flag
MOVERS (shift over k-sigma, sigma from centroid error plus field scatter) and
VARIABLES (flux change over k-sigma at matched wavelength). Confirm movers as
plus/minus dipoles in the difference image. Cross-match Gaia DR3: known stars get
"known, Gaia predicts X, we measure Y". Unmatched red movers get "unlisted
candidate, needs checking". Show clickable markers and a ranked list.

**C. Truth check.** Batch script: pick 20 to 40 unsaturated high-proper-motion
Gaia DR3 stars, measure first-to-last-visit displacement with this pipeline, plot
measured vs Gaia-predicted with a 1:1 line and RMS. Add a `/validation` page and
put the plot in the README.

**B. Spectrum on click.** Forced aperture photometry at the clicked position on
every exposure from all six detectors. Wavelength from the spectral WCS at that
position, errors from VARIANCE. Plot flux vs wavelength 0.75 to 5 microns, colored
by visit, flagged points greyed. Follow the source's per-visit position if it
moves. Mark water ice ~3.0, methane ~3.3, CO2 ~4.27, CO ~4.67 microns as labeled
guides. Add a per-visit light curve.

**D. Context.** Aladin Lite panel at the same position. Gaia DR3 sources drawn on
the SPHEREx frames with arrows showing predicted motion.

Tag `v2` when A and C work.

## Phase 4 — ship

- Re-run `export_showcase.py` so `docs/` includes candidates, spectra, and the
  validation page for the five presets.
- README: what it is, the wavelength-fair blink idea, validation plot, how to run,
  how to update for new data releases, a "Network calls" list, Data & Credits
  (SPHEREx/IRSA with its DOI and acknowledgement text, Gaia/ESA, CDS for Aladin
  Lite), licenses of every library.
- AI disclosure: header comment in every source file saying it was AI-assisted
  with Claude Code. `AI_USAGE.md` logging what AI built per phase, with this spec
  and the session prompts saved under `docs/prompts/`. Leave the section titled
  'Human decisions and testing' for the human author to fill in.
- Demo assets in `demo/`: blink GIFs and short MP4 clips, plus a storyboard for a
  video of **30 seconds maximum** with English subtitles. No AI-generated images.
  No NASA logos, insignia, or mission patches anywhere.
- `SUBMISSION.md`: draft text for each form field (summary, detailed description,
  NASA data used, other data and tools, use of AI).

## Privacy rules

- No analytics, trackers, or telemetry. Server binds to localhost only.
- Browser-side external requests: only the Aladin Lite CDN. Server-side: only
  IRSA and PyPI.
- Nothing personal in the repo: no real name, school, email, absolute paths,
  usernames, or hostnames in code, logs, or commits. `.gitignore` the cache.

## Stack

Python 3.11+, fastapi, uvicorn, astropy, astroquery, reproject, sep, numpy, scipy,
pillow, imageio. pytest for coordinate parsing, visit clustering, and URL building.
