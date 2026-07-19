"""Encode a proposed fix inside a review issue, and read it back to apply it.

The review-first flow is two-phase: DocSentry opens an issue describing the
drift and the fix it can apply, then — only when a human approves — applies that
*exact* fix. To apply the reviewed fix rather than re-guessing (the model is
non-deterministic, and the drift may have moved), the issue carries the fix as a
hidden, machine-readable payload.

The payload is base64-encoded JSON in an HTML comment, so it renders invisibly
on GitHub and cannot collide with the comment delimiter whatever the fix text
contains.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

_MARKER = "docsentry:fix:v1"
_RE = re.compile(r"<!--\s*" + re.escape(_MARKER) + r"\s+([A-Za-z0-9+/=]+)\s*-->")

# Only the fields the apply step needs to reconstruct a verdict + change.
_FIX_KEYS = ("doc_id", "doc_file", "doc_heading", "doc_start_line",
             "doc_end_line", "suggested_fix", "mismatch", "confidence")
_CHANGE_KEYS = ("file", "kind", "name", "detail")


def encode_fix(verdict: dict[str, Any], change: dict[str, Any],
               commit_hash: str) -> str:
    """Return the hidden HTML-comment payload for a review issue."""
    payload = {
        "commit": commit_hash,
        "change": {k: change.get(k, "") for k in _CHANGE_KEYS},
        "verdict": {k: verdict.get(k, "") for k in _FIX_KEYS},
    }
    blob = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f"<!-- {_MARKER} {blob} -->"


def decode_fix(issue_body: str) -> dict[str, Any] | None:
    """Extract the fix payload from an issue body, or None if absent/corrupt.

    Returns {"commit", "change", "verdict"} where verdict is shaped like a
    divergence verdict, so auto_fixer can render and open the fix directly.
    """
    if not issue_body:
        return None
    m = _RE.search(issue_body)
    if not m:
        return None
    try:
        data = json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "verdict" not in data or "change" not in data:
        return None

    v = data["verdict"]
    # Coerce the line numbers back to ints; JSON kept them, but be defensive.
    for key in ("doc_start_line", "doc_end_line"):
        try:
            v[key] = int(v.get(key) or 0)
        except (TypeError, ValueError):
            v[key] = 0
    return data
