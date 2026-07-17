"""The VERIFY step: before shipping a fix, confirm the doc no longer lies."""
from __future__ import annotations

import logging
from typing import Any

from docsentry.agents.divergence import verify_correction

log = logging.getLogger(__name__)


def verify_fix(change: dict[str, Any], fixed_doc_content: str,
               verdict: dict[str, Any]) -> tuple[bool, str]:
    """Confirm a drafted fix resolves the specific claim it was meant to.

    Returns (passed, reason). Fails closed: an unreachable model means
    "unverified", not "clean", so an LLM outage can never let an unchecked PR
    through. v1 returned a bare `not recheck["diverged"]`, which read an error
    verdict as a pass.

    The check is deliberately NOT a fresh divergence run. Re-judging the
    corrected doc against the same change ("safe: True -> False") led the model
    to latch onto the old value and "confirm" a divergence the fix had already
    resolved, so a genuinely correct fix was downgraded to an issue. It now
    asks the narrow question — is the specific known lie gone? — with the doc
    presented as already corrected. See divergence.verify_correction.
    """
    if not fixed_doc_content.strip():
        return False, "the proposed fix is empty"

    result = verify_correction(change, verdict.get("mismatch", ""), fixed_doc_content)

    if result["error"]:
        return False, f"could not verify: {result['error']}"
    if not result["resolved"]:
        return False, f"the fix still diverges: {result['reason']}"
    return True, result["reason"]
