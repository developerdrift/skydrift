# AI-assisted: written with Claude Code (Anthropic). See AI_USAGE.md.
"""Live coverage index: which exposures contain a sky position, from everything scanned so far.

The background daemon (scripts/coverage_daemon.py) keeps appending S3 header records to
cache/s3index/headers.jsonl. Any record whose footprint contains a position is coverage for
that position, so lookups improve on their own as the daemon runs. The app never scans; it
calls lookup() (fast, incremental) and request() (queues a position for the daemon).

Files:
  cache/s3index/headers.jsonl          one JSON record per exposure header read
  cache/coverage/<name>.jsonl          covering exposures per daemon target, appended live
  cache/coverage/<name>.status.json    daemon progress for that target
  cache/coverage/queue/<ra>_<dec>.json positions requested by the app
"""
import json
import threading
import time
from pathlib import Path

import numpy as np

from .s3scan import contains

_LOCK = threading.Lock()
_INDEXES = {}


def _xyz(ra, dec):
    r, d = np.radians(ra), np.radians(dec)
    return np.stack([np.cos(d) * np.cos(r), np.cos(d) * np.sin(r), np.sin(d)], axis=-1)


class LiveIndex:
    """Incrementally reads headers.jsonl (only complete lines, from the last offset)."""

    def __init__(self, root):
        self.path = Path(root) / "s3index" / "headers.jsonl"
        self.offset = 0
        self.recs = []
        self.xyz = np.zeros((0, 3))

    def refresh(self):
        if not self.path.exists():
            return
        with self.path.open("rb") as f:
            f.seek(self.offset)
            chunk = f.read()
        end = chunk.rfind(b"\n")
        if end < 0:
            return
        new = []
        for line in chunk[:end].splitlines():
            try:
                new.append(json.loads(line))
            except ValueError:
                pass
        self.offset += end + 1
        if new:
            self.recs += new
            self.xyz = np.vstack([self.xyz, _xyz(np.array([r["ra"] for r in new]),
                                                 np.array([r["dec"] for r in new]))])

    def lookup(self, ra, dec, max_center_deg=3.0):
        self.refresh()
        if not self.recs:
            return []
        cosd = self.xyz @ _xyz(ra, dec)
        cand = np.nonzero(cosd > np.cos(np.radians(max_center_deg)))[0]
        seen, out = set(), []
        for i in cand:
            r = self.recs[i]
            if r["key"] not in seen and contains(r["fp"], ra, dec):
                seen.add(r["key"])
                out.append(r)
        return sorted(out, key=lambda r: r["mjd"])


def lookup(ra, dec, root):
    with _LOCK:
        key = str(Path(root).resolve())
        if key not in _INDEXES:
            _INDEXES[key] = LiveIndex(root)
        return _INDEXES[key].lookup(ra, dec)


def queue_dir(root):
    d = Path(root) / "coverage" / "queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


def request(ra, dec, root, name=None):
    """Ask the daemon to search this position (no-op if already queued or done)."""
    tag = f"{ra:.4f}_{dec:+.4f}"
    q = queue_dir(root) / f"{tag}.json"
    if q.exists() or status(ra, dec, root) is not None:
        return
    q.write_text(json.dumps(dict(ra=ra, dec=dec, name=name or tag, t=time.time())))


def status(ra, dec, root, name=None):
    """Daemon status for this position: by name, by tag, or any target within ~0.4 arcsec."""
    d = Path(root) / "coverage"
    for tag in filter(None, [name, f"{ra:.4f}_{dec:+.4f}"]):
        p = d / f"{tag}.status.json"
        if p.exists():
            try:
                return json.loads(p.read_text())
            except ValueError:
                pass
    for p in d.glob("*.status.json") if d.exists() else []:
        try:
            st = json.loads(p.read_text())
        except ValueError:
            continue
        if abs(st.get("ra", 999) - ra) < 1e-4 and abs(st.get("dec", 999) - dec) < 1e-4:
            return st
    return None
