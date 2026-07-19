"""Approval-gated fixes: payload round-trip, pipeline routing, apply/dismiss."""
from __future__ import annotations

import pytest

from docsentry.agents.review import decode_fix, encode_fix

VERDICT = {
    "doc_id": "README.md::38", "doc_file": "README.md", "doc_heading": "round_to",
    "doc_start_line": 38, "doc_end_line": 47, "confidence": 0.9,
    "mismatch": "defaults to 2 places",
    "suggested_fix": "## round_to\n\nDefaults to **10** places.\n\n```py\n# --> not a delimiter\n```",
}
CHANGE = {"file": "calculator.py", "kind": "default_changed",
          "name": "round_to", "detail": "`round_to` default changed: `2` → `10`"}


# --- payload --------------------------------------------------------------

def test_encode_is_an_invisible_html_comment():
    marker = encode_fix(VERDICT, CHANGE, "abc123")
    assert marker.startswith("<!--")
    assert marker.endswith("-->")
    # No raw fix text leaks into the marker (it is base64), so it can't collide
    # with the --> delimiter even though the fix contains one.
    assert "round_to" not in marker
    assert "-->" not in marker[:-3]


def test_round_trip_recovers_the_fix():
    body = f"Some prose.\n\n{encode_fix(VERDICT, CHANGE, 'abc123')}\n\nMore prose."
    data = decode_fix(body)
    assert data["commit"] == "abc123"
    assert data["change"]["name"] == "round_to"
    assert data["verdict"]["suggested_fix"] == VERDICT["suggested_fix"]
    assert data["verdict"]["doc_start_line"] == 38
    assert data["verdict"]["doc_end_line"] == 47


def test_decode_returns_none_without_a_payload():
    assert decode_fix("just a normal issue body") is None
    assert decode_fix("") is None


def test_decode_tolerates_corruption():
    assert decode_fix("<!-- docsentry:fix:v1 not-valid-base64!! -->") is None


def test_line_numbers_come_back_as_ints():
    data = decode_fix(encode_fix(VERDICT, CHANGE, "x"))
    assert isinstance(data["verdict"]["doc_start_line"], int)


# --- pipeline routing -----------------------------------------------------

DIVERGED = {
    "diverged": True, "confidence": 0.95,
    "mismatch": "The doc says 2; it is now 10.",
    "suggested_fix": "## round_to\n\nDefaults to **10**.",
}
CLEAN = {"diverged": False, "confidence": 0.9, "mismatch": "", "suggested_fix": ""}


@pytest.fixture
def capture_actions(monkeypatch):
    calls = {"review": [], "issue": [], "pr": []}
    monkeypatch.setattr("docsentry.pipeline.open_review_issue",
                        lambda v, c, **k: calls["review"].append((v, c, k))
                        or "https://gh/issues/1")
    monkeypatch.setattr("docsentry.pipeline.open_docs_lie_issue",
                        lambda v, c, **k: calls["issue"].append((v, c)) or "https://gh/issues/2")
    monkeypatch.setattr("docsentry.pipeline.open_fix_pr",
                        lambda v, c, **k: calls["pr"].append((v, c)) or "https://gh/pull/3")
    return calls


def _head(local_repo):
    from docsentry.core.git_ops import latest_commit_hash
    return latest_commit_hash(local_repo)


def test_approval_mode_opens_a_review_issue_not_a_pr(local_repo, fake_llm,
                                                     capture_actions, isolated_settings):
    from docsentry.pipeline import RunOptions, run_pipeline
    isolated_settings.require_approval = True
    fake_llm.replies = [DIVERGED, CLEAN]  # divergence, then the review's self-check

    results = run_pipeline(_head(local_repo), RunOptions(require_approval=True))

    assert [r["status"] for r in results] == ["needs_approval"]
    assert len(capture_actions["review"]) == 1
    assert not capture_actions["pr"]      # nothing applied without approval
    assert results[0]["url"] == "https://gh/issues/1"


def test_approval_mode_carries_the_verified_note(local_repo, fake_llm,
                                                 capture_actions, isolated_settings):
    from docsentry.pipeline import RunOptions, run_pipeline
    isolated_settings.require_approval = True
    fake_llm.replies = [DIVERGED, CLEAN]
    run_pipeline(_head(local_repo), RunOptions(require_approval=True))
    _, _, kwargs = capture_actions["review"][0]
    assert "resolves the drift" in kwargs["verified"]


def test_approval_mode_no_fix_falls_back_to_alert(local_repo, fake_llm,
                                                  capture_actions, isolated_settings):
    from docsentry.pipeline import RunOptions, run_pipeline
    isolated_settings.require_approval = True
    # diverged but the model proposed no fix -> a plain alert, not a review.
    fake_llm.reply = {"diverged": True, "confidence": 0.7,
                      "mismatch": "wrong", "suggested_fix": ""}
    results = run_pipeline(_head(local_repo), RunOptions(require_approval=True))
    assert [r["status"] for r in results] == ["alerted"]
    assert capture_actions["issue"] and not capture_actions["review"]


def test_approval_mode_skips_below_alert_threshold(local_repo, fake_llm,
                                                   capture_actions, isolated_settings):
    from docsentry.pipeline import RunOptions, run_pipeline
    fake_llm.reply = {**DIVERGED, "confidence": 0.1}
    results = run_pipeline(_head(local_repo),
                           RunOptions(require_approval=True))
    assert [r["status"] for r in results] == ["low_confidence_skip"]
    assert not capture_actions["review"] and not capture_actions["issue"]


def test_approval_mode_never_verifies_as_a_gate(local_repo, fake_llm,
                                                capture_actions, isolated_settings):
    """Even if the self-check says 'still diverges', approval mode still opens a
    review (the human decides) — it does not silently drop the finding."""
    fake_llm.replies = [DIVERGED, DIVERGED]  # divergence, then a failing recheck
    results = run_pipeline_helper(local_repo)
    assert [r["status"] for r in results] == ["needs_approval"]
    _, _, kwargs = capture_actions["review"][0]
    assert "could not fully confirm" in kwargs["verified"]


def run_pipeline_helper(local_repo):
    from docsentry.pipeline import RunOptions, run_pipeline
    return run_pipeline(_head(local_repo), RunOptions(require_approval=True))
