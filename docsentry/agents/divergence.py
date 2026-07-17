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
