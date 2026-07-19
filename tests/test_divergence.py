"""Verdict parsing and the divergence/verify agents, with the model faked."""
from __future__ import annotations

import pytest

from docsentry.agents.divergence import check_divergence
from docsentry.agents.verifier import verify_fix
from docsentry.llm import LLMError
from docsentry.llm.client import parse_verdict

CHANGE = {
    "file": "calculator.py",
    "kind": "default_changed",
    "name": "divide",
    "detail": "`divide` default for `safe` changed: `True` → `False`",
}
DOC = {
    "id": "README.md::10",
    "content": "## divide\n\nBy default `safe` is **True**.",
    "meta": {"file": "README.md", "heading": "divide",
             "start_line": 10, "end_line": 12},
}

DIVERGED = {
    "diverged": True, "confidence": 0.95,
    "mismatch": "The doc says safe defaults to True; it is now False.",
    "suggested_fix": "## divide\n\nBy default `safe` is **False**.",
}

# What check_divergence returns: the model's verdict plus the doc's identity.
VERDICT = {
    **DIVERGED,
    "doc_id": DOC["id"],
    "doc_file": "README.md",
    "doc_heading": "divide",
    "doc_start_line": 10,
    "doc_end_line": 12,
}


# --- parse_verdict --------------------------------------------------------

def test_parses_bare_json():
    v = parse_verdict('{"diverged": true, "confidence": 0.9, "mismatch": "x",'
                      ' "suggested_fix": "y"}')
    assert v["diverged"] is True
    assert v["confidence"] == 0.9


def test_parses_fenced_json():
    """Small local models wrap JSON in markdown fences."""
    raw = '```json\n{"diverged": false, "confidence": 0.2}\n```'
    assert parse_verdict(raw)["diverged"] is False


def test_parses_json_buried_in_prose():
    raw = 'Sure! Here is my answer:\n{"diverged": true, "confidence": 0.8,' \
          ' "mismatch": "m"}\nHope that helps!'
    v = parse_verdict(raw)
    assert v["diverged"] is True
    assert v["mismatch"] == "m"


def test_rescales_percentage_confidence():
    """Models routinely answer 90 instead of 0.9; taken literally that clears
    every threshold at once."""
    assert parse_verdict('{"diverged": true, "confidence": 90}')["confidence"] == 0.9


def test_confidence_clamped_to_unit_range():
    assert parse_verdict('{"confidence": -5}')["confidence"] == 0.0
    assert parse_verdict('{"confidence": 100}')["confidence"] == 1.0


def test_non_numeric_confidence_is_zero():
    assert parse_verdict('{"diverged": true, "confidence": "high"}')["confidence"] == 0.0


def test_unparseable_reply_is_not_diverged():
    v = parse_verdict("I have no idea what you want.")
    assert v["diverged"] is False
    assert "UNPARSEABLE" in v["mismatch"]


def test_empty_reply_is_not_diverged():
    assert parse_verdict("")["diverged"] is False


def test_json_array_reply_is_not_diverged():
    assert parse_verdict("[1, 2, 3]")["diverged"] is False


# --- check_divergence -----------------------------------------------------

def test_diverged_verdict_carries_doc_metadata(fake_llm):
    fake_llm.reply = DIVERGED
    v = check_divergence(CHANGE, DOC)
    assert v["diverged"] is True
    assert v["doc_file"] == "README.md"
    assert v["doc_heading"] == "divide"
    assert v["doc_start_line"] == 10
    assert v["doc_end_line"] == 12
    assert v["error"] is None


def test_prompt_includes_change_and_doc(fake_llm):
    fake_llm.reply = DIVERGED
    check_divergence(CHANGE, DOC)
    system, user = fake_llm.calls[0]
    assert "divide" in user
    assert "By default `safe` is **True**" in user
    # Groq's JSON mode requires the literal word "json" in the prompt.
    assert "json" in system.lower()


def test_diverged_without_a_mismatch_is_downgraded(fake_llm):
    """A 'diverged' verdict with no explanation is not actionable and would
    file an empty issue."""
    fake_llm.reply = {"diverged": True, "confidence": 0.9,
                      "mismatch": "   ", "suggested_fix": ""}
    v = check_divergence(CHANGE, DOC)
    assert v["diverged"] is False


def test_llm_error_is_captured_not_raised(fake_llm):
    fake_llm.error = LLMError("groq is down")
    v = check_divergence(CHANGE, DOC)
    assert v["diverged"] is False
    assert v["error"] == "groq is down"
    assert "LLM ERROR" in v["mismatch"]


# --- verify_fix -----------------------------------------------------------

def test_verify_passes_when_recheck_is_clean(fake_llm):
    fake_llm.reply = {"diverged": False, "confidence": 0.9,
                      "mismatch": "", "suggested_fix": ""}
    passed, reason = verify_fix(CHANGE, "## divide\n\nsafe is False.", VERDICT)
    assert passed is True
    assert reason


def test_verify_fails_when_fix_still_diverges(fake_llm):
    fake_llm.reply = DIVERGED
    passed, reason = verify_fix(CHANGE, "## divide\n\nstill wrong", VERDICT)
    assert passed is False
    assert "still diverges" in reason


def test_verify_fails_closed_on_llm_error(fake_llm):
    """The critical one: v1 returned `not recheck["diverged"]`, so an LLM
    outage produced diverged=False and read as a PASS — shipping an unverified
    fix precisely when the verifier was broken."""
    fake_llm.error = LLMError("timeout")
    passed, reason = verify_fix(CHANGE, "## divide\n\nanything", VERDICT)
    assert passed is False
    assert "could not verify" in reason


def test_verify_rejects_empty_fix(fake_llm):
    passed, reason = verify_fix(CHANGE, "   ", VERDICT)
    assert passed is False
    assert "empty" in reason
    # The model must not even be consulted about an empty fix.
    assert fake_llm.calls == []


def test_verify_asks_the_verification_question_not_detection(fake_llm):
    """Regression guard for the real Groq failure: re-running the detection
    prompt made the model latch onto the old value in the change and reject a
    correct fix. Verification must use its own prompt, anchored on the known
    lie, with the doc presented as already corrected."""
    from docsentry.agents.divergence import SYSTEM, SYSTEM_VERIFY

    fake_llm.reply = {"diverged": False, "confidence": 0.95,
                      "mismatch": "", "suggested_fix": ""}
    verify_fix(CHANGE, "## divide\n\nsafe is False now.", VERDICT)

    system, user = fake_llm.calls[0]
    assert system == SYSTEM_VERIFY
    assert system != SYSTEM
    # The prompt must carry the specific claim that was wrong and the corrected
    # text, so the model judges "is this fixed?" rather than re-deriving.
    assert VERDICT["mismatch"] in user
    assert "safe is False now." in user
    assert "CORRECTED" in user


def test_verify_correction_maps_the_schema(fake_llm):
    """diverged=false in the reply means the fix worked (resolved)."""
    from docsentry.agents.divergence import verify_correction

    fake_llm.reply = {"diverged": False, "confidence": 0.9, "mismatch": "",
                      "suggested_fix": ""}
    good = verify_correction(CHANGE, "safe was said to be True", "corrected text")
    assert good["resolved"] is True
    assert good["error"] is None

    fake_llm.reply = {"diverged": True, "confidence": 0.8,
                      "mismatch": "still says True", "suggested_fix": ""}
    bad = verify_correction(CHANGE, "safe was said to be True", "still wrong text")
    assert bad["resolved"] is False
    assert bad["reason"] == "still says True"
