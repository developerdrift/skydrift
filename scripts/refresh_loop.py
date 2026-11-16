# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Periodic refresh until a deadline, then a final refresh and a regression check.

Usage: python scripts/refresh_loop.py --every 30 --until 21:30
After the deadline (and once the coverage daemon has stopped writing), it runs:
  final refresh -> pytest -> static docs/ check (node, all 5 presets) -> validation page check.
Results: cache/refresh_loop.log, cache/final_check.json. Exit code 0 only if every check passed.
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "cache" / "refresh_loop.log"
PY = sys.executable


def log(*m):
    line = time.strftime("%H:%M:%S ") + " ".join(map(str, m))
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_refresh():
    r = subprocess.run([PY, str(ROOT / "scripts" / "refresh.py")], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    st = json.loads((ROOT / "cache" / "refresh_status.json").read_text())
    log("refresh done:", json.dumps({k: st.get(k) for k in ("finished", "truth", "export", "seconds")}),
        "| exposures:", {k: v.get("exposures") for k, v in st["presets"].items()}, "| rc", r.returncode)
    return st


def final_check():
    res = {}
    r = subprocess.run([PY, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True, errors="replace")
    res["pytest"] = dict(ok=r.returncode == 0, tail=r.stdout.strip().splitlines()[-1:] if r.stdout else [])
    srv = subprocess.Popen([PY, "-m", "http.server", "8799", "-d", "docs", "--bind", "127.0.0.1"], cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(2)
        r = subprocess.run(["node", "scripts/check_static.js", "docs/static/app.js", "http://127.0.0.1:8799/"],
                           cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=600)
        res["static"] = dict(ok=r.returncode == 0, out=r.stdout.strip().splitlines())
        v = {}
        for path in ("validation.html", "static/validation.js", "static/validation/truth.json",
                     "static/validation/truth_plot.png"):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:8799/{path}", timeout=20) as resp:
                    body = resp.read()
                    v[path] = resp.status == 200 and len(body) > 100
                    if path.endswith("truth.json"):
                        tj = json.loads(body)
                        v["truth_has_rows"] = len(tj.get("rows", [])) > 0
            except Exception as e:  # noqa: BLE001
                v[path] = f"error {type(e).__name__}"
        res["validation"] = dict(ok=all(x is True for x in v.values()), detail=v)
    finally:
        srv.terminate()
    res["all_ok"] = all(res[k]["ok"] for k in ("pytest", "static", "validation"))
    (ROOT / "cache" / "final_check.json").write_text(json.dumps(res, indent=1))
    log("FINAL CHECK", "OK" if res["all_ok"] else "FAILED", json.dumps(res)[:1500])
    return res["all_ok"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=float, default=30)
    ap.add_argument("--until", default="21:30")
    a = ap.parse_args()
    now = dt.datetime.now()
    end = now.replace(hour=int(a.until[:2]), minute=int(a.until[3:5]), second=0, microsecond=0)
    log(f"refresh loop: every {a.every} min until {end:%H:%M}")
    while True:
        nxt = time.time() + a.every * 60
        run_refresh()
        if dt.datetime.now() >= end:
            break
        time.sleep(max(0, min(nxt, end.timestamp()) - time.time()))
        if dt.datetime.now() >= end:
            break
    # let the daemon finish its last write (it stops at the same deadline)
    daemon_log = ROOT / "cache" / "coverage" / "daemon.log"
    for _ in range(30):
        if daemon_log.exists() and "daemon done" in daemon_log.read_text(errors="replace")[-3000:]:
            break
        time.sleep(30)
    log("deadline reached: final refresh + regression check")
    run_refresh()
    sys.exit(0 if final_check() else 1)


if __name__ == "__main__":
    main()
