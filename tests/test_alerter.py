"""The 'Docs Lie' issue body — it must not itself lie."""
from __future__ import annotations

from docsentry.agents.alerter import _body, _confidence_note
from docsentry.config import settings

VERDICT = {
    "doc_file": "README.md", "doc_heading": "round_to",
    "doc_start_line": 38, "doc_end_line": 47,
    "confidence": 0.9, "mismatch": "defaults to 2 places",
    "suggested_fix": "## round_to\n\nDefaults to **8** places.",
}
CHANGE = {"detail": "`round_to` default changed: `6` → `8`", "file": "calculator.py"}


def test_below_threshold_says_below_threshold():
    note = _confidence_note(0.6, "")
    assert "below" in note
    assert f"{settings.autofix_threshold:.0%}" in note


def test_high_confidence_escalation_does_not_claim_below_threshold():
    """The bug this guards: an issue opened via the escalation path (auto-fix
    blocked) carried a 90% confidence but said 'below the 85% threshold'. The
    tool that catches lying docs was lying in its own issue."""
    note = _confidence_note(0.9, "")
    assert "below" not in note
    assert "PR" in note or "human" in note


def test_explicit_reason_wins():
    note = _confidence_note(0.9, "GitHub blocked the PR (403)")
    assert note == "GitHub blocked the PR (403)"


def test_body_reflects_the_real_reason():
    body = _body(VERDICT, CHANGE, reason="the fix could not be opened as a PR")
    assert "90%" in body
    assert "the fix could not be opened as a PR" in body
    assert "below the" not in body
    # The suggested fix is included so a human can apply it.
    assert "Defaults to **8** places." in body


def test_body_for_a_plain_alert_is_accurate():
    low = {**VERDICT, "confidence": 0.6}
    body = _body(low, CHANGE)
    assert "60%" in body
    assert "below the" in body
