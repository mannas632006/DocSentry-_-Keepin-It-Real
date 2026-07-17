"""Link a semantic code change to the doc sections it may invalidate."""
from __future__ import annotations

import re
from typing import Any

from docsentry.core import retrieval

# How many candidates to pull before re-ranking. Retrieving exactly n and then
# boosting cannot promote a section that missed the cut, so the pool is wider
# than the result set.
_POOL_FACTOR = 4
_MIN_POOL = 12


def _mentions(name: str, text: str) -> bool:
    """True when text names this identifier exactly.

    A substring test would let `divide` match `divided` or `safe_divide`, which
    is exactly the kind of false link that produces a bogus issue.
    """
    return re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", text) is not None


def link_change_to_docs(change: dict[str, Any], n: int = 3) -> list[dict[str, Any]]:
    """Doc sections most likely to describe this change, best first.

    change is one SemanticChange dict from the ChangeReport.
    """
    query = f"{change['name']} {change['detail']}"
    pool = max(n * _POOL_FACTOR, _MIN_POOL)
    hits = retrieval.search(query, n=pool)

    for h in hits:
        h["exact_match"] = _mentions(change["name"], h["content"])

    # An exact mention of the identifier beats any lexical score: if a section
    # names the function, it is talking about the function.
    hits.sort(key=lambda h: (not h["exact_match"], -h["score"]))
    return hits[:n]
