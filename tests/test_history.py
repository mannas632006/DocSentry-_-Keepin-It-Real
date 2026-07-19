"""Portable JSON run-history for the serverless (GitHub Action) mode."""
from __future__ import annotations

import json

from docsentry.history import append_run, load_runs, make_record


def _finding(status="alerted"):
    return {"status": status, "change": {"name": "divide", "detail": "d"},
            "doc": {"file": "README.md", "start_line": 7, "end_line": 11},
            "confidence": 0.9, "mismatch": "m", "suggested_fix": "", "url": "u"}


def test_append_creates_file(tmp_path):
    p = tmp_path / "history.json"
    append_run(p, make_record("abc", [_finding()], repo="a/b"))
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["count"] == 1
    assert data["runs"][0]["commit"] == "abc"
    assert data["runs"][0]["repo"] == "a/b"
    assert data["runs"][0]["id"] == 1


def test_append_accumulates_with_monotonic_ids(tmp_path):
    p = tmp_path / "history.json"
    append_run(p, make_record("a", [_finding()]))
    append_run(p, make_record("b", [_finding()]))
    runs = load_runs(p)
    assert [r["commit"] for r in runs] == ["a", "b"]
    assert [r["id"] for r in runs] == [1, 2]


def test_history_is_capped(tmp_path):
    p = tmp_path / "history.json"
    for i in range(5):
        append_run(p, make_record(f"c{i}", []), max_runs=3)
    runs = load_runs(p)
    assert len(runs) == 3
    # The oldest are dropped; the newest survive with rising ids.
    assert [r["commit"] for r in runs] == ["c2", "c3", "c4"]
    assert [r["id"] for r in runs] == [3, 4, 5]


def test_load_missing_file_is_empty(tmp_path):
    assert load_runs(tmp_path / "nope.json") == []


def test_load_tolerates_corruption(tmp_path):
    p = tmp_path / "history.json"
    p.write_text("this is not json", encoding="utf-8")
    assert load_runs(p) == []
    # And a subsequent append recovers rather than crashing.
    append_run(p, make_record("a", []))
    assert len(load_runs(p)) == 1


def test_load_accepts_bare_list(tmp_path):
    """A history file that is a plain array (not wrapped in {runs:...})."""
    p = tmp_path / "history.json"
    p.write_text(json.dumps([{"id": 1, "commit": "x", "results": []}]), encoding="utf-8")
    assert load_runs(p)[0]["commit"] == "x"


def test_record_shape_matches_db(tmp_path):
    """The record must carry the same keys the dashboard reads from the DB."""
    rec = make_record("abc", [_finding()], commit_msg="msg", duration_ms=12,
                      dry_run=True, repo="a/b")
    assert set(rec) >= {"commit", "commit_msg", "repo", "ts", "duration_ms",
                        "trigger", "dry_run", "error", "results"}
    assert rec["dry_run"] is True
    assert rec["results"][0]["status"] == "alerted"
