"""Tiny SQLite layer for pipeline run history."""
import json
import sqlite3
import time
from pathlib import Path

DB = Path("docsentry.db")


def _conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_hash TEXT, ts REAL, results TEXT)""")


def save_run(commit_hash: str, results: list[dict]):
    with _conn() as c:
        c.execute("INSERT INTO runs (commit_hash, ts, results) VALUES (?,?,?)",
                  (commit_hash, time.time(), json.dumps(results)))


def recent_runs(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r["id"], "commit": r["commit_hash"], "ts": r["ts"],
             "results": json.loads(r["results"])} for r in rows]
