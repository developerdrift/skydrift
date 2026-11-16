# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""SkyDrift local server. Binds to 127.0.0.1 only. No analytics, no external browser calls.

Run:  .venv/Scripts/python -m app.server      then open http://127.0.0.1:8000/
"""
import json
import threading
import time
import traceback
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from engine import coverage, fetch, views
from engine.coords import CoordError, parse_dec, parse_fov, parse_ra
from engine.targets import preset_positions

warnings.filterwarnings("ignore")
import logging  # noqa: E402
logging.getLogger("astropy").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache"
STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="SkyDrift", docs_url=None, redoc_url=None)
(CACHE / "views").mkdir(parents=True, exist_ok=True)
app.mount("/views", StaticFiles(directory=CACHE / "views"), name="views")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_jobs = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=2)


def presets():
    return preset_positions()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/validation")
def validation():
    return FileResponse(STATIC / "validation.html")


@app.get("/api/presets")
def api_presets():
    return dict(mode="live", presets=presets(), tap=fetch.tap_available())


def _run(job_id, ra, dec, fov, force=False):
    def prog(stage, frac):
        with _lock:
            _jobs[job_id].update(stage=stage, frac=round(float(frac), 3))
    try:
        views.build_view(ra, dec, fov, CACHE, progress=prog, force=force)
        with _lock:
            _jobs[job_id].update(status="done", frac=1.0,
                                 base=f"/views/{views.view_dir(CACHE, ra, dec, fov).name}/")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        with _lock:
            _jobs[job_id].update(status="error", error=f"{type(e).__name__}: {e}"[:300])


@app.get("/api/view")
def api_view(ra: str, dec: str, fov: str = "6"):
    try:
        ra_d, dec_d, fov_v = round(parse_ra(ra), 5), round(parse_dec(dec), 5), parse_fov(fov)
    except CoordError as e:
        raise HTTPException(400, str(e))
    vd = views.view_dir(CACHE, ra_d, dec_d, fov_v)
    mp = vd / "manifest.json"
    if mp.exists():
        # Rebuild automatically if the background scan has found more exposures since.
        man = json.loads(mp.read_text())
        now = len(fetch.find_exposures(ra_d, dec_d, views.cutout_size(fov_v), CACHE))
        if now <= man.get("n_found", 0):
            return dict(status="done", base=f"/views/{vd.name}/", ra=ra_d, dec=dec_d, fov=fov_v)
    key = vd.name
    with _lock:
        for jid, j in _jobs.items():
            if j["key"] == key and j["status"] == "running":
                return dict(status="running", job=jid, ra=ra_d, dec=dec_d, fov=fov_v)
        jid = uuid.uuid4().hex[:12]
        _jobs[jid] = dict(key=key, status="running", stage="queued", frac=0.0, started=time.time())
    _pool.submit(_run, jid, ra_d, dec_d, fov_v, mp.exists())
    return dict(status="running", job=jid, ra=ra_d, dec=dec_d, fov=fov_v)


@app.get("/api/coverage")
def api_coverage(ra: float, dec: float):
    """Background-scan status for a position (preset name or ra/dec tag)."""
    name = next((p["key"] for p in presets() if abs(p["ra"] - ra) < 1e-4 and abs(p["dec"] - dec) < 1e-4), None)
    return coverage.status(ra, dec, CACHE, name) or dict(state="not scanned yet (queued)")


@app.get("/api/spectrum")
def api_spectrum(base: str, x: float, y: float):
    """Forced photometry on every exposure at a clicked grid pixel of a built view."""
    from engine import regrid, spectrum
    name = Path(base.strip("/")).name
    mp = CACHE / "views" / name / "manifest.json"
    if not mp.exists():
        raise HTTPException(404, "unknown view")
    man = json.loads(mp.read_text())
    w, _ = regrid.target_wcs(man["ra"], man["dec"], man["fov"])
    fol, snapped = spectrum.follow_for(man, x, y, w)
    sp = spectrum.spectrum(man, CACHE, fol)
    return dict(sp, x=x, y=y, snapped=snapped.get("kind") if snapped else None)


@app.get("/api/job/{jid}")
def api_job(jid: str):
    with _lock:
        j = _jobs.get(jid)
        if not j:
            raise HTTPException(404, "unknown job")
        return JSONResponse({k: v for k, v in j.items() if k != "started"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
