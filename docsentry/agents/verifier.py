"""The VERIFY step: before shipping a fix, confirm the doc no longer lies."""
from __future__ import annotations

import logging
from typing import Any

from docsentry.agents.divergence import check_divergence

log = logging.getLogger(__name__)


def verify_fix(change: dict[str, Any], fixed_doc_content: str,
               verdict: dict[str, Any]) -> tuple[bool, str]:
    """Re-run divergence against the patched section.

    Returns (passed, reason). Fails closed: an unreachable model means
    "unverified", not "clean", so an LLM outage can never let an unchecked PR
    through. v1 returned a bare `not recheck["diverged"]`, which read an error
    verdict as a pass.
    """
    if not fixed_doc_content.strip():
        return False, "the proposed fix is empty"

    patched_section = {
        "id": verdict["doc_id"],
        "content": fixed_doc_content,
        "meta": {
            "file": verdict["doc_file"],
            "heading": verdict["doc_heading"],
            "start_line": verdict["doc_start_line"],
            "end_line": verdict["doc_end_line"],
        },
    }
    recheck = check_divergence(change, patched_section)

    if recheck.get("error"):
        return False, f"could not verify: {recheck['error']}"
    if recheck["diverged"]:
        return False, f"the fix still diverges: {recheck['mismatch']}"
    return True, "re-checked clean against the same change"
