"""Portable JSON run-history for environments without the SQLite server.

The GitHub Action runs statelessly — no persistent database, no server — so it
records each run to a plain JSON file that the static dashboard reads. The run
record uses the same shape as core.db, so one dashboard renders either source.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

MAX_RUNS = 500


def load_runs(path: str | Path) -> list[dict[str, Any]]:
    """Read the run list from a history file. Tolerant of absence/corruption."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        runs = data.get("runs", [])
    elif isinstance(data, list):
        runs = data
    else:
        runs = []
    return [r for r in runs if isinstance(r, dict)]


def make_record(commit: str, results: list[dict[str, Any]], *,
                commit_msg: str = "", duration_ms: int = 0,
                trigger: str = "action", dry_run: bool = False,
                error: str = "", repo: str = "") -> dict[str, Any]:
    """Build one run record, matching the db.recent_runs() shape.

    `repo` ("owner/name") lets the dashboard build GitHub links; it is not in
    the db shape because the server already knows its own target_repo.
    """
    return {
        "commit": commit,
        "commit_msg": commit_msg,
        "repo": repo,
        "ts": time.time(),
        "duration_ms": duration_ms,
        "trigger": trigger,
        "dry_run": dry_run,
        "error": error,
        "results": results,
    }


def append_run(path: str | Path, record: dict[str, Any],
               max_runs: int = MAX_RUNS) -> dict[str, Any]:
    """Append a run record to the history file, capped to the most recent runs.

    Runs are stored oldest-first with a monotonic id; the dashboard sorts by
    timestamp. Returns the written payload.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    runs = load_runs(p)
    next_id = max((r.get("id", 0) for r in runs), default=0) + 1
    runs.append({"id": next_id, **record})
    runs = runs[-max_runs:]

    payload = {"generated_at": time.time(), "count": len(runs), "runs": runs}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
