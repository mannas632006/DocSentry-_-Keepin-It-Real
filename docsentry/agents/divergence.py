"""The REASON step: does this doc section now make a false claim?"""
from __future__ import annotations

import logging
from typing import Any

from docsentry.llm import LLMError, complete_json

log = logging.getLogger(__name__)

SYSTEM = """You are DocSentry, an agent that detects when documentation no \
longer matches code behaviour.

You will receive:
1. A semantic code change (what changed in the code)
2. A documentation section that may describe that code

Decide whether the documentation now contains a false or outdated statement \
*because of this change*.

Respond with ONLY a JSON object, no markdown fences and no prose:
{
  "diverged": true | false,
  "confidence": 0.0-1.0,
  "mismatch": "one sentence naming the doc claim that is now false, else empty",
  "suggested_fix": "the COMPLETE corrected section, else empty"
}

Rules:
- diverged=true ONLY when the doc states something this change contradicts.
- A newly added function that the docs simply do not mention is NOT divergence:
  missing documentation is not lying documentation. Return diverged=false.
- A pure docstring or comment edit that leaves behaviour unchanged is NOT
  divergence.
- confidence is how certain you are of the verdict, calibrated honestly:
  >=0.9 the doc verbatim states the old behaviour; 0.7-0.9 strongly implies it;
  0.4-0.7 possibly related; <0.4 you are guessing.
- suggested_fix MUST be the entire section rewritten, reproduced verbatim
  except for the parts that are wrong. It replaces the section wholesale, so
  omitting the unchanged lines deletes them. Include the original heading line.
  Preserve the surrounding tone and markdown formatting.
- If diverged=false, both mismatch and suggested_fix must be empty strings."""


# Verification is a different question from detection, and asking it as the same
# question is a real trap. Re-running check_divergence passes the same change
# ("safe: True -> False") against the corrected doc; the change text names both
# the old and new values, and models routinely latch onto the wrong one and
# "confirm" a divergence that the fix already resolved. Instead, verification is
# anchored on the *specific* claim that was wrong and told the doc is already a
# correction — a narrow yes/no, not a fresh open-ended judgement.
# Same JSON schema as detection (diverged/confidence/mismatch), so the shared
# parser applies unchanged, but a sharper question: given a doc that has ALREADY
# been corrected, does it STILL contain a false claim? diverged=true here means
# the fix did not work.
SYSTEM_VERIFY = """You are DocSentry's verifier. A documentation section was \
found to contain a false claim, and a correction has already been drafted. Your \
only job is to confirm the correction is now accurate before it ships.

You will receive:
1. The code change that made the original text false.
2. The specific false claim that was identified.
3. The PROPOSED CORRECTED documentation (already rewritten).

Respond with ONLY a JSON object, no markdown fences and no prose:
{
  "diverged": true | false,
  "confidence": 0.0-1.0,
  "mismatch": "one sentence naming what is STILL false, else empty"
}

Rules:
- diverged=FALSE means the correction is good: it accurately reflects the
  behaviour after the code change and the identified false claim is gone. This
  is the expected outcome when the fix did its job.
- diverged=TRUE ONLY if the corrected text still states something the change
  contradicts, or introduces a NEW false claim about this change. Do not flag a
  doc merely for describing the changed behaviour correctly.
- Judge only the corrected text as written. Missing detail the section never set
  out to cover is not a false claim.
- The code change is the source of truth for current behaviour."""


def _user_message(change: dict[str, Any], doc_section: dict[str, Any]) -> str:
    meta = doc_section["meta"]
    return f"""CODE CHANGE:
File: {change['file']}
Kind: {change['kind']}
Detail: {change['detail']}

DOCUMENTATION SECTION ({meta['file']}, lines {meta['start_line']}-{meta['end_line']}):
---
{doc_section['content']}
---"""


def _verify_message(change: dict[str, Any], mismatch: str, fixed_content: str) -> str:
    return f"""CODE CHANGE:
File: {change['file']}
Kind: {change['kind']}
Detail: {change['detail']}

THE FALSE CLAIM THAT WAS IDENTIFIED:
{mismatch or '(not specified)'}

PROPOSED CORRECTED DOCUMENTATION:
---
{fixed_content}
---"""


def verify_correction(change: dict[str, Any], mismatch: str,
                      fixed_content: str) -> dict[str, Any]:
    """Confirm a drafted fix resolves the specific claim it was meant to.

    Returns {resolved, confidence, reason, error}. Never raises: an unreachable
    model yields resolved=False carrying the error, so the caller fails closed
    rather than shipping an unverified fix.
    """
    try:
        raw = complete_json(SYSTEM_VERIFY, _verify_message(change, mismatch, fixed_content))
    except LLMError as e:
        log.error("verification failed: %s", e)
        return {"resolved": False, "confidence": 0.0, "reason": str(e), "error": str(e)}

    still_wrong = raw["diverged"]
    return {
        "resolved": not still_wrong,
        "confidence": raw["confidence"],
        "reason": raw["mismatch"] if still_wrong else "correction reflects the change",
        "error": None,
    }


def check_divergence(change: dict[str, Any], doc_section: dict[str, Any]) -> dict[str, Any]:
    """Judge one (change, doc section) pair.

    Never raises: an unreachable model yields a non-diverged verdict carrying
    the error, so one bad call cannot abort a whole run.
    """
    error: str | None = None
    try:
        verdict = complete_json(SYSTEM, _user_message(change, doc_section))
    except LLMError as e:
        log.error("divergence check failed: %s", e)
        error = str(e)
        verdict = {
            "diverged": False,
            "confidence": 0.0,
            "mismatch": f"LLM ERROR: {e}",
            "suggested_fix": "",
        }
    # Distinguishable from a genuine "not diverged": the verifier must not read
    # an unreachable model as proof that a fix is clean.
    verdict["error"] = error

    # A diverged verdict with no mismatch text is not actionable, and models
    # occasionally return one; treat it as a non-finding rather than filing an
    # empty issue.
    if verdict["diverged"] and not verdict["mismatch"].strip():
        verdict["diverged"] = False
        verdict["confidence"] = 0.0

    meta = doc_section["meta"]
    verdict["doc_id"] = doc_section["id"]
    verdict["doc_file"] = meta["file"]
    verdict["doc_heading"] = meta["heading"]
    verdict["doc_start_line"] = meta["start_line"]
    verdict["doc_end_line"] = meta["end_line"]
    return verdict
