# Submission drafts (NASA Space Apps 2026: "Planet X and SPHEREx")

> These are drafts for you to edit. Numbers are from the final snapshot (`PROGRESS.md` → "Final numbers").

## Project name
SkyDrift

## Summary (short)
SkyDrift turns SPHEREx's all-sky images into a blink comparator anyone can use. Enter a position
(or tap a preset) and watch that patch of sky across visits months apart, so stars that move or
change stand out. Because SPHEREx sees every spot at a different wavelength in each exposure, a
naive blink flickers for no real reason. SkyDrift stacks each detector per visit, so only real
changes remain. It then flags movers and variables automatically and checks its own measurements
against known nearby stars.

## Detailed description
**What it does.**
- Shows a blink of SPHEREx images of any position: per-visit stacks for each of the six detectors
  (0.75-5 µm), single exposures with their wavelength, an all-epoch stack, and a difference image.
- Labels every frame with date, days since the first frame, wavelength, observation IDs, release
  and flagged-pixel statistics.
- Settings live in the URL, and an "Embed this view" button gives an iframe snippet.
- A static version of the five presets runs with no server (`docs/`).

**How it works.**
- Exposures covering a position are found and cutouts fetched from IRSA. ZODI is subtracted, and
  pixels are masked with the SPHEREx team's documented photometry flag list.
- Everything is reprojected to a common north-up 3.1"/px grid, then stacked per visit and
  detector with inverse-variance weights. One shared stretch is used per sequence.
- Candidates: sources are detected in each visit stack and matched between first and last visits,
  and the field's median offset is removed.
  - Movers are shifts above 5σ, confirmed by a +/− pair in the difference image.
  - Variables are flux changes above 5σ, claimed only where the two visits cover overlapping
    wavelengths.

**Results so far (real SPHEREx data).**
- **WISE 0855-0714** (the coldest known brown dwarf) is detected at ~4.6 µm and invisible at
  ~1 µm. Its motion is recovered in D6: about 4" in 5.5 months, matching the predicted direction
  (measured 4.07" vs predicted 4.61", position angle 281° vs 277°).
- **RW Aurigae** is flagged as variable: flux ×1.7 relative to the field, at overlapping
  wavelengths.
- **Truth check:** 48 measurements of 29 known high-proper-motion stars, 35 consistent with the
  prediction. Vector RMS 0.85″ for the consistent measurements and 1.86″ over all, outliers kept
  (one SPHEREx pixel is 6.2″). Comparison values are literature numbers, not live Gaia queries.

**Honest limits.**
- IRSA's query services (TAP/SIA/cone search) were down during the whole build. SkyDrift found
  data by reading file headers from IRSA's public S3 bucket, a sampled search that misses some
  exposures.
- Comparison proper motions are literature values, not live Gaia queries.
- Bright stars such as Barnard's Star saturate. Candidates are candidates, not discoveries.

## NASA data used
- SPHEREx Level-2 spectral images (DR1 and QR3) from the NASA/IPAC Infrared Science Archive
  (IRSA): the public `nasa-irsa-spherex` bucket and the IRSA cutout service.
- SPHEREx Explanatory Supplement (IRSA), for the pixel flag definitions.

## Other data and tools
- Literature proper motions and parallaxes for known nearby stars and brown dwarfs (Gaia DR3 /
  published astrometry, quoted because IRSA's Gaia service was unreachable).
- Python: astropy, astroquery, numpy, scipy, reproject, sep, pillow, imageio, matplotlib,
  requests, FastAPI, uvicorn, pytest. Plain HTML/JS frontend with no frameworks.

## Use of AI
AI-assisted, human-led. I led this project from idea to release: I set the
goals, made the engineering decisions, tested the results, and shipped it.
The code was written with AI assistance (Claude Code, Anthropic), working from
specifications and prompts I directed. No AI-generated images or video, and no
NASA branding. The specification and selected prompts are in docs/prompts/.
