"""SQLite persistence for run history and alert de-duplication.

v1 stored each run as a single JSON blob, which meant the dashboard had to
fetch every row and filter in Python. Findings now get their own table so the
API can filter, search and paginate in SQL.

The database lives at an absolute path derived from the package location.
v1 used a bare relative "docsentry.db", so the agent quietly used a different
database depending on which directory you launched it from.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from docsentry.config import settings

SCHEMA_VERSION = 3


def _db_file() -> Path:
    path = settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# Which database file the schema has been created in this process. The FastAPI
# server calls init_db() on startup, but the CLI and the pipeline do not — so
# any DB access self-heals via _ensure_schema() rather than failing with
# "no such table". Keyed on the path so a config change (or a test switching
# data_dir) re-initialises the new file.
_schema_ready_for: str | None = None


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Raw connection, no schema guard. Used by init_db itself."""
    c = sqlite3.connect(_db_file(), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    _ensure_schema()
    with _connect() as c:
        yield c


def _ensure_schema() -> None:
    global _schema_ready_for
    path = str(_db_file())
    if _schema_ready_for != path:
        init_db()
        _schema_ready_for = path


def init_db() -> None:
    global _schema_ready_for
    _create_schema()
    _schema_ready_for = str(_db_file())


def _create_schema() -> None:
    # Uses the raw connection so it cannot recurse through _ensure_schema.
    with _connect() as c:
        version = c.execute("PRAGMA user_version").fetchone()[0]
        if version and version < SCHEMA_VERSION:
            # v1 rows have an incompatible shape and no findings table. The
            # history is a local cache of GitHub state, not a source of truth,
            # so rebuilding is cheaper than migrating.
            c.executescript("DROP TABLE IF EXISTS findings; DROP TABLE IF EXISTS runs;")

        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_hash  TEXT NOT NULL,
                commit_msg   TEXT DEFAULT '',
                ts           REAL NOT NULL,
                duration_ms  INTEGER DEFAULT 0,
                trigger      TEXT DEFAULT 'manual',
                dry_run      INTEGER DEFAULT 0,
                error        TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS findings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id        INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                status        TEXT NOT NULL,
                change_file   TEXT DEFAULT '',
                change_kind   TEXT DEFAULT '',
                change_name   TEXT DEFAULT '',
                change_detail TEXT DEFAULT '',
                doc_file      TEXT DEFAULT '',
                doc_heading   TEXT DEFAULT '',
                -- The line range the finding is about. Persisted so the stored
                -- finding matches the shape the pipeline produces, and so a
                -- reader can link straight to the offending lines.
                doc_start     INTEGER DEFAULT 0,
                doc_end       INTEGER DEFAULT 0,
                confidence    REAL DEFAULT 0,
                mismatch      TEXT DEFAULT '',
                suggested_fix TEXT DEFAULT '',
                url           TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS alerts (
                key         TEXT PRIMARY KEY,
                url         TEXT NOT NULL,
                commit_hash TEXT DEFAULT '',
                ts          REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_findings_run    ON findings(run_id);
            CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);
            CREATE INDEX IF NOT EXISTS idx_runs_ts         ON runs(ts DESC);
            """
        )
        c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


# --- writes ---------------------------------------------------------------


def save_run(
    commit_hash: str,
    results: list[dict[str, Any]],
    *,
    commit_msg: str = "",
    duration_ms: int = 0,
    trigger: str = "manual",
    dry_run: bool = False,
    error: str = "",
) -> int:
    """Persist one pipeline run and its findings. Returns the run id."""
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO runs (commit_hash, commit_msg, ts, duration_ms, trigger,"
            " dry_run, error) VALUES (?,?,?,?,?,?,?)",
            (commit_hash, commit_msg, time.time(), duration_ms, trigger,
             int(dry_run), error),
        )
        run_id = cur.lastrowid
        for r in results:
            change = r.get("change") or {}
            doc = r.get("doc") or {}
            c.execute(
                "INSERT INTO findings (run_id, status, change_file, change_kind,"
                " change_name, change_detail, doc_file, doc_heading, doc_start,"
                " doc_end, confidence, mismatch, suggested_fix, url)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    r.get("status", "unknown"),
                    change.get("file", ""),
                    change.get("kind", ""),
                    change.get("name", ""),
                    change.get("detail", ""),
                    doc.get("file", ""),
                    doc.get("heading", ""),
                    int(doc.get("start_line") or 0),
                    int(doc.get("end_line") or 0),
                    float(r.get("confidence") or 0.0),
                    r.get("mismatch", "") or "",
                    r.get("suggested_fix", "") or "",
                    r.get("url", "") or "",
                ),
            )
        return run_id


def clear_runs() -> int:
    """Wipe run history and the alert dedup log. Returns runs deleted."""
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        c.executescript("DELETE FROM findings; DELETE FROM runs; DELETE FROM alerts;")
        return n


# --- alert de-duplication -------------------------------------------------


def alert_key(doc_file: str, doc_heading: str, change_name: str,
              change_detail: str) -> str:
    """Stable identity for 'this doc section, wrong in this specific way'.

    Keyed on the change detail rather than the commit, so re-pushing or
    re-running against the same drift reuses the existing issue instead of
    filing a duplicate.
    """
    raw = "|".join([doc_file, doc_heading, change_name, change_detail])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def find_alert(key: str) -> str | None:
    """URL of an alert already filed for this key, if any."""
    with _conn() as c:
        row = c.execute("SELECT url FROM alerts WHERE key = ?", (key,)).fetchone()
        return row["url"] if row else None


def record_alert(key: str, url: str, commit_hash: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO alerts (key, url, commit_hash, ts) VALUES (?,?,?,?)",
            (key, url, commit_hash, time.time()),
        )


# --- reads ----------------------------------------------------------------

# Free-text search clause, shared by recent_runs and count_runs so the two can
# never disagree about what matches.
_SEARCH_SQL = (
    "(runs.commit_hash LIKE ?1 OR runs.commit_msg LIKE ?1 OR EXISTS ("
    " SELECT 1 FROM findings f WHERE f.run_id = runs.id AND ("
    " f.change_detail LIKE ?1 OR f.doc_file LIKE ?1"
    " OR f.doc_heading LIKE ?1 OR f.mismatch LIKE ?1)))"
)
_STATUS_SQL = (
    "EXISTS (SELECT 1 FROM findings f WHERE f.run_id = runs.id AND f.status = ?)"
)


def _filters(status: str | None, q: str | None) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    if q:
        where.append(_SEARCH_SQL)
        params.append(f"%{q}%")
    if status:
        where.append(_STATUS_SQL)
        params.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return clause, params


def _finding_row(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": r["id"],
        "status": r["status"],
        "change": {
            "file": r["change_file"],
            "kind": r["change_kind"],
            "name": r["change_name"],
            "detail": r["change_detail"],
        },
        "doc": {
            "file": r["doc_file"],
            "heading": r["doc_heading"],
            "start_line": r["doc_start"],
            "end_line": r["doc_end"],
        },
        "confidence": r["confidence"],
        "mismatch": r["mismatch"],
        "suggested_fix": r["suggested_fix"],
        "url": r["url"],
    }


def _run_row(r: sqlite3.Row, findings: list[sqlite3.Row]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "commit": r["commit_hash"],
        "commit_msg": r["commit_msg"],
        "ts": r["ts"],
        "duration_ms": r["duration_ms"],
        "trigger": r["trigger"],
        "dry_run": bool(r["dry_run"]),
        "error": r["error"],
        "results": [_finding_row(f) for f in findings],
    }


def recent_runs(limit: int = 50, offset: int = 0, status: str | None = None,
                q: str | None = None) -> list[dict[str, Any]]:
    """Runs newest-first, each with its findings.

    status keeps runs containing at least one finding of that status; q is a
    free-text match over commit, change detail, doc file/heading and mismatch.
    """
    clause, params = _filters(status, q)
    sql = f"SELECT * FROM runs {clause} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?"
    with _conn() as c:
        rows = c.execute(sql, (*params, limit, offset)).fetchall()
        out = []
        for r in rows:
            findings = c.execute(
                "SELECT * FROM findings WHERE run_id = ? ORDER BY id", (r["id"],)
            ).fetchall()
            out.append(_run_row(r, findings))
        return out


def get_run(run_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not r:
            return None
        findings = c.execute(
            "SELECT * FROM findings WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return _run_row(r, findings)


def count_runs(status: str | None = None, q: str | None = None) -> int:
    clause, params = _filters(status, q)
    with _conn() as c:
        return c.execute(f"SELECT COUNT(*) FROM runs {clause}", params).fetchone()[0]


def stats() -> dict[str, Any]:
    with _conn() as c:
        total_runs = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        by_status = {
            r["status"]: r["n"]
            for r in c.execute(
                "SELECT status, COUNT(*) AS n FROM findings GROUP BY status"
            ).fetchall()
        }
        last = c.execute("SELECT ts FROM runs ORDER BY ts DESC LIMIT 1").fetchone()
        avg_ms = c.execute(
            "SELECT AVG(duration_ms) FROM runs WHERE duration_ms > 0"
        ).fetchone()[0]
        return {
            "total_runs": total_runs,
            "total_findings": sum(by_status.values()),
            "auto_fixed": by_status.get("auto_fixed", 0),
            "alerted": by_status.get("alerted", 0),
            "clean": by_status.get("clean", 0),
            "skipped": by_status.get("low_confidence_skip", 0),
            "escalated": by_status.get("fix_failed_verification", 0),
            "by_status": by_status,
            "last_run_ts": last["ts"] if last else None,
            "avg_duration_ms": int(avg_ms) if avg_ms else 0,
        }
