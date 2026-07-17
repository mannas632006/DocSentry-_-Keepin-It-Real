"""HTTP surface: webhook, read API, guarded write API."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from docsentry.config import settings
from docsentry.core import db
from docsentry.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "test-secret")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def no_llm(monkeypatch):
    """/health probes the model; keep it off the network."""
    monkeypatch.setattr("docsentry.main.probe", lambda: {
        "provider": "groq", "model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1", "reachable": True,
    })


def _sign(body: bytes, secret: str = "test-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _push(commit="abc123", ref="refs/heads/main", **extra) -> bytes:
    return json.dumps({"ref": ref, "after": commit, **extra}).encode()


# --- health / config ------------------------------------------------------

def test_health_reports_ready(client, no_llm):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert body["status"] == "ok"
    assert body["problems"] == []


def test_health_reports_missing_config(client, monkeypatch, no_llm):
    """The API must boot without config and say what is missing, rather than
    crash on import the way v1 did."""
    monkeypatch.setattr(settings, "github_token", "")
    body = client.get("/health").json()
    assert body["ready"] is False
    assert body["status"] == "degraded"
    assert any("github_token" in p for p in body["problems"])


def test_health_reports_unreachable_llm(client, monkeypatch):
    monkeypatch.setattr("docsentry.main.probe", lambda: {
        "provider": "groq", "model": "m", "base_url": "u",
        "reachable": False, "error": "connection refused",
    })
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["llm"]["reachable"] is False


def test_config_never_leaks_secrets(client):
    body = client.get("/api/config").json()
    assert body["github_token_set"] is True
    assert body["llm_api_key_set"] is True
    # The values themselves must not appear anywhere in the payload.
    blob = json.dumps(body)
    assert "test-token" not in blob
    assert "test-key" not in blob


# --- webhook --------------------------------------------------------------

def test_webhook_rejects_missing_signature(client):
    assert client.post("/webhook/github", content=_push()).status_code == 401


def test_webhook_rejects_bad_signature(client):
    body = _push()
    r = client.post("/webhook/github", content=body,
                    headers={"X-Hub-Signature-256": _sign(body, "wrong-secret"),
                             "X-GitHub-Event": "push"})
    assert r.status_code == 401


def test_webhook_accepts_signed_push(client, monkeypatch):
    seen = []
    monkeypatch.setattr("docsentry.main._process",
                        lambda c, t, o: seen.append((c, t)) or 1)
    body = _push("deadbeef")
    r = client.post("/webhook/github", content=body,
                    headers={"X-Hub-Signature-256": _sign(body),
                             "X-GitHub-Event": "push"})
    assert r.status_code == 200
    assert r.json() == {"queued": "deadbeef"}
    assert seen == [("deadbeef", "webhook")]


def test_webhook_answers_ping(client):
    """GitHub pings the moment you add the hook; a non-200 shows as a failed
    delivery."""
    body = json.dumps({"zen": "hi"}).encode()
    r = client.post("/webhook/github", content=body,
                    headers={"X-Hub-Signature-256": _sign(body),
                             "X-GitHub-Event": "ping"})
    assert r.status_code == 200
    assert r.json()["pong"] is True


def test_webhook_ignores_non_push_events(client):
    body = _push()
    r = client.post("/webhook/github", content=body,
                    headers={"X-Hub-Signature-256": _sign(body),
                             "X-GitHub-Event": "issues"})
    assert r.json() == {"ignored": "issues"}


def test_webhook_ignores_own_fix_branches(client, monkeypatch):
    """Otherwise the agent analyses the branch it just pushed, forever."""
    called = []
    monkeypatch.setattr("docsentry.main._process", lambda *a: called.append(a))
    body = _push(ref="refs/heads/docsentry/fix-abc123")
    r = client.post("/webhook/github", content=body,
                    headers={"X-Hub-Signature-256": _sign(body),
                             "X-GitHub-Event": "push"})
    assert r.json() == {"ignored": "own branch"}
    assert called == []


def test_webhook_ignores_branch_deletion(client):
    body = _push(commit="0" * 40, deleted=True)
    r = client.post("/webhook/github", content=body,
                    headers={"X-Hub-Signature-256": _sign(body),
                             "X-GitHub-Event": "push"})
    assert r.json() == {"ignored": "branch deleted"}


def test_webhook_ignores_zero_commit(client):
    body = _push(commit="0" * 40)
    r = client.post("/webhook/github", content=body,
                    headers={"X-Hub-Signature-256": _sign(body),
                             "X-GitHub-Event": "push"})
    assert r.json() == {"ignored": "no commit"}


# --- read API -------------------------------------------------------------

def test_runs_empty(client):
    body = client.get("/api/runs").json()
    assert body == {"total": 0, "limit": 25, "offset": 0, "runs": []}


def test_runs_filter_and_paginate(client):
    db.init_db()
    db.save_run("aaa", [{"status": "clean", "change": {"name": "add"},
                         "doc": {"file": "README.md"}}])
    db.save_run("bbb", [{"status": "alerted", "change": {"name": "divide"},
                         "doc": {"file": "README.md"}, "url": "https://x/1"}])

    assert client.get("/api/runs").json()["total"] == 2
    filtered = client.get("/api/runs", params={"status": "alerted"}).json()
    assert filtered["total"] == 1
    assert filtered["runs"][0]["commit"] == "bbb"

    paged = client.get("/api/runs", params={"limit": 1}).json()
    assert len(paged["runs"]) == 1
    assert paged["total"] == 2


def test_runs_rejects_silly_limits(client):
    assert client.get("/api/runs", params={"limit": 0}).status_code == 422
    assert client.get("/api/runs", params={"limit": 9999}).status_code == 422


def test_single_run(client):
    db.init_db()
    run_id = db.save_run("aaa", [{"status": "clean", "change": {}, "doc": {}}])
    assert client.get(f"/api/runs/{run_id}").json()["commit"] == "aaa"
    assert client.get("/api/runs/9999").status_code == 404


def test_stats(client):
    db.init_db()
    db.save_run("aaa", [{"status": "alerted", "change": {}, "doc": {}}])
    body = client.get("/api/stats").json()
    assert body["total_runs"] == 1
    assert body["alerted"] == 1


# --- write API ------------------------------------------------------------

def test_write_endpoints_disabled_without_admin_token(client):
    """The service runs on a public URL. With no admin_token configured these
    must be closed, not open — an anonymous trigger files real issues."""
    r = client.post("/api/analyze", json={})
    assert r.status_code == 403
    assert "admin_token" in r.json()["detail"]
    assert client.delete("/api/runs").status_code == 403


def test_analyze_requires_the_right_token(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    assert client.post("/api/analyze", json={}).status_code == 401
    r = client.post("/api/analyze", json={}, headers={"X-Admin-Token": "wrong"})
    assert r.status_code == 401


def test_analyze_queues_a_run(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    monkeypatch.setattr("docsentry.main._process", lambda c, t, o: 1)
    r = client.post("/api/analyze", json={"commit": "abc123", "dry_run": True},
                    headers={"X-Admin-Token": "s3cret"})
    assert r.status_code == 200
    assert r.json()["queued"] == "abc123"
    assert r.json()["options"]["dry_run"] is True


def test_analyze_blocked_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    monkeypatch.setattr(settings, "target_repo", "")
    r = client.post("/api/analyze", json={"commit": "abc"},
                    headers={"X-Admin-Token": "s3cret"})
    assert r.status_code == 409


def test_analyze_validates_thresholds(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    r = client.post("/api/analyze", json={"autofix_threshold": 5},
                    headers={"X-Admin-Token": "s3cret"})
    assert r.status_code == 422


def test_clear_runs(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    db.init_db()
    db.save_run("aaa", [{"status": "clean", "change": {}, "doc": {}}])
    r = client.delete("/api/runs", headers={"X-Admin-Token": "s3cret"})
    assert r.json() == {"deleted": 1}
    assert client.get("/api/runs").json()["total"] == 0
