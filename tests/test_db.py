"""Run history, filtering and alert de-duplication."""
from __future__ import annotations

import pytest

from docsentry.core import db


@pytest.fixture(autouse=True)
def _fresh_db():
    db.init_db()
    yield


def _finding(status="alerted", detail="`divide` default changed", doc="README.md",
             heading="divide", confidence=0.7, url="https://gh/issue/1"):
    return {
        "status": status,
        "change": {"file": "calculator.py", "kind": "default_changed",
                   "name": "divide", "detail": detail},
        "doc": {"file": doc, "heading": heading},
        "confidence": confidence,
        "mismatch": "doc says True",
        "suggested_fix": "## divide\n\nFalse",
        "url": url,
    }


def test_save_and_read_round_trip():
    run_id = db.save_run("abc123", [_finding()], commit_msg="flip default",
                         duration_ms=42, trigger="manual")
    run = db.get_run(run_id)
    assert run["commit"] == "abc123"
    assert run["commit_msg"] == "flip default"
    assert run["duration_ms"] == 42
    assert run["trigger"] == "manual"
    assert len(run["results"]) == 1
    f = run["results"][0]
    assert f["status"] == "alerted"
    assert f["change"]["name"] == "divide"
    assert f["doc"]["file"] == "README.md"
    assert f["confidence"] == 0.7


def test_finding_doc_keeps_its_line_range():
    """The documented Finding contract promises doc.start_line/end_line. They
    used to be silently dropped on the way into SQLite, so a stored finding had
    a different shape from the one the pipeline produced."""
    run_id = db.save_run("abc", [_finding() | {
        "doc": {"file": "README.md", "heading": "divide",
                "start_line": 7, "end_line": 11},
    }])
    doc = db.get_run(run_id)["results"][0]["doc"]
    assert doc == {"file": "README.md", "heading": "divide",
                   "start_line": 7, "end_line": 11}


def test_finding_without_a_line_range_defaults_to_zero():
    """Findings like no_semantic_changes carry no doc at all."""
    run_id = db.save_run("abc", [{"status": "no_semantic_changes",
                                  "change": {}, "doc": {}}])
    doc = db.get_run(run_id)["results"][0]["doc"]
    assert doc["start_line"] == 0
    assert doc["end_line"] == 0


def test_get_missing_run_is_none():
    assert db.get_run(999) is None


def test_runs_are_newest_first():
    db.save_run("aaa", [_finding()])
    db.save_run("bbb", [_finding()])
    assert [r["commit"] for r in db.recent_runs()] == ["bbb", "aaa"]


def test_run_with_no_findings():
    run_id = db.save_run("empty", [])
    assert db.get_run(run_id)["results"] == []


def test_error_is_persisted():
    run_id = db.save_run("bad", [], error="clone failed")
    assert db.get_run(run_id)["error"] == "clone failed"


def test_filter_by_status():
    db.save_run("aaa", [_finding(status="clean")])
    db.save_run("bbb", [_finding(status="alerted")])

    alerted = db.recent_runs(status="alerted")
    assert [r["commit"] for r in alerted] == ["bbb"]
    assert db.count_runs(status="alerted") == 1
    assert db.count_runs(status="clean") == 1
    assert db.count_runs() == 2


def test_search_matches_change_detail():
    db.save_run("aaa", [_finding(detail="`divide` default changed", heading="divide")])
    db.save_run("bbb", [_finding(detail="`add` signature changed", heading="add")])
    assert [r["commit"] for r in db.recent_runs(q="divide")] == ["aaa"]
    assert db.count_runs(q="divide") == 1


def test_search_matches_commit_and_doc():
    db.save_run("deadbeef", [_finding(doc="GUIDE.md")])
    assert db.count_runs(q="deadbeef") == 1
    assert db.count_runs(q="GUIDE") == 1
    assert db.count_runs(q="nothing-matches") == 0


def test_status_and_search_combine():
    """Both filters at once — the SQL mixes numbered and positional params, so
    this pins that they bind in the right order."""
    db.save_run("aaa", [_finding(status="clean", detail="about divide",
                                 heading="divide")])
    db.save_run("bbb", [_finding(status="alerted", detail="about divide",
                                 heading="divide")])
    db.save_run("ccc", [_finding(status="alerted", detail="about add",
                                 heading="add")])

    hits = db.recent_runs(status="alerted", q="divide")
    assert [r["commit"] for r in hits] == ["bbb"]
    assert db.count_runs(status="alerted", q="divide") == 1


def test_pagination():
    for i in range(5):
        db.save_run(f"c{i}", [_finding()])
    page = db.recent_runs(limit=2, offset=2)
    assert len(page) == 2
    assert db.count_runs() == 5


def test_stats_counts_by_status():
    db.save_run("aaa", [_finding(status="clean"), _finding(status="alerted")])
    db.save_run("bbb", [_finding(status="auto_fixed")], duration_ms=100)

    s = db.stats()
    assert s["total_runs"] == 2
    assert s["total_findings"] == 3
    assert s["clean"] == 1
    assert s["alerted"] == 1
    assert s["auto_fixed"] == 1
    assert s["avg_duration_ms"] == 100
    assert s["last_run_ts"] is not None


def test_stats_on_empty_db():
    s = db.stats()
    assert s["total_runs"] == 0
    assert s["avg_duration_ms"] == 0
    assert s["last_run_ts"] is None


# --- dedup ----------------------------------------------------------------

def test_alert_key_is_stable():
    a = db.alert_key("README.md", "divide", "divide", "default changed")
    b = db.alert_key("README.md", "divide", "divide", "default changed")
    assert a == b


def test_alert_key_varies_with_every_component():
    base = db.alert_key("README.md", "divide", "divide", "default changed")
    assert base != db.alert_key("GUIDE.md", "divide", "divide", "default changed")
    assert base != db.alert_key("README.md", "add", "divide", "default changed")
    assert base != db.alert_key("README.md", "divide", "add", "default changed")
    assert base != db.alert_key("README.md", "divide", "divide", "other change")


def test_find_alert_returns_recorded_url():
    key = db.alert_key("README.md", "divide", "divide", "d")
    assert db.find_alert(key) is None
    db.record_alert(key, "https://gh/issue/7", "abc")
    assert db.find_alert(key) == "https://gh/issue/7"


def test_record_alert_is_idempotent():
    key = db.alert_key("README.md", "divide", "divide", "d")
    db.record_alert(key, "https://gh/issue/7")
    db.record_alert(key, "https://gh/issue/8")
    assert db.find_alert(key) == "https://gh/issue/8"


def test_clear_runs_wipes_everything():
    db.save_run("aaa", [_finding()])
    db.record_alert(db.alert_key("a", "b", "c", "d"), "https://gh/1")
    assert db.clear_runs() == 1
    assert db.recent_runs() == []
    assert db.stats()["total_runs"] == 0
    assert db.find_alert(db.alert_key("a", "b", "c", "d")) is None


def test_init_db_is_idempotent():
    db.init_db()
    db.init_db()
    assert db.stats()["total_runs"] == 0


def test_db_self_initialises_without_explicit_init(tmp_path, monkeypatch):
    """Regression: the CLI and pipeline never call init_db(), so the first DB
    access must create the schema on demand. Without this, an armed (non-dry)
    run hit the alert-dedup path and died with 'no such table: alerts' — while
    every dry run passed, because dry-run returns before touching the DB."""
    from docsentry.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "never-inited")
    monkeypatch.setattr(db, "_schema_ready_for", None)  # mimic a fresh process

    # No init_db() here — exactly what the alerter does.
    assert db.find_alert("k") is None
    db.record_alert("k", "https://x/1")
    assert db.find_alert("k") == "https://x/1"
    # And a full run persists too, still without an explicit init.
    rid = db.save_run("abc", [_finding()])
    assert db.get_run(rid)["commit"] == "abc"


def test_db_lives_under_data_dir(isolated_settings):
    db.save_run("aaa", [])
    assert isolated_settings.db_path.is_file()
    assert isolated_settings.data_dir in isolated_settings.db_path.parents
