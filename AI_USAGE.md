# AI usage

SkyDrift was built with AI assistance: Claude Code (Anthropic), working from the
specification and selected prompts saved in `docs/prompts/`. Every source file carries a header saying it was
AI-assisted. No AI-generated images are used anywhere: every image comes from SPHEREx data or
from plots of it.

## What the AI built, per phase

**Phase 0 (data proof).**
- Probed the IRSA TAP schema (`spherex.plane`, `spherex.artifact`). TAP, SIA and cone search
  then went down IRSA-wide.
- Found a fallback: list the public IRSA S3 bucket, read file headers by HTTP range request, and
  fetch pixels from the IRSA cutout service.
- Wrote `probe.py` and `probe_s3.py`.
- Took the FLAGS bit meanings from the official SPHEREx Explanatory Supplement, not from guesses.
- Tested two hypotheses for WISE 0855's reference epoch and reported both.

**Phase 1 (engine).** Wrote `engine/`:
- fetch with disk cache, plus the S3 header scan;
- calibration (ZODI subtraction, the documented photometry flag mask, residual background);
- regridding to a north-up 3.1"/px grid;
- inverse-variance stacks per visit and detector;
- shared-stretch rendering.

It also wrote the synthetic-data tests (logic checks only) and the Barnard's Star acceptance GIF.

**Phase 2 / 2S (app and static showcase).**
- FastAPI server bound to localhost.
- Plain HTML/JS blink player: four modes, URL state, embed, presets, metadata, progress.
- Live coverage index with automatic view rebuild.
- `export_showcase.py`, and a headless checker that drives the real `app.js` (`scripts/check_static.js`).
- A background coverage daemon and a periodic refresh job.

**Phase 3A (candidates).** `engine/candidates.py`:
- source detection with `sep` and first-to-last matching;
- field-offset removal and k-sigma movers with a dipole check;
- variability claimed only at overlapping wavelengths;
- markers and a ranked list in the UI.

**Phase 3B (spectrum on click).**
- `engine/spectrum.py`: forced photometry on every exposure at a clicked position, following a
  confirmed mover's measured motion, plus a per-visit light curve.
- `/api/spectrum`, spectra precomputed for the static showcase, and canvas plots.
- Phase 3D (context panel) was not built (scope decision).

**Phase 3C (truth check).**
- `scripts/truth_check.py` and the `/validation` page.
- Prediction includes annual parallax.
- Comparison values are literature numbers quoted from memory, because Gaia was unreachable, and
  are labelled as such.

**Phase 4 (ship).** README sections, this file, `SUBMISSION.md` drafts, the demo assets script
and storyboard.

## Known limitations the AI reported rather than hid

- Coverage comes from a sampled S3 header scan, not a complete query, so some exposures are missed.
- The proper motions and positions used for checks are not live Gaia DR3 values.
- Barnard's Star is saturated. Its acceptance GIF shows the saturated core for display only.
- Phase 0's first coverage numbers were wrong because of a listing bug (retry directories). It
  was found, fixed and documented in `PROGRESS.md`.

## Human decisions and testing

AI-assisted, human-led. I led this project from idea to release: I set the
goals, made the engineering decisions, tested the results, and shipped it.
The code was written with AI assistance (Claude Code, Anthropic), working from
specifications and prompts I directed.
