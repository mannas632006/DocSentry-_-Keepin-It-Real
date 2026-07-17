"""Linking a code change to the doc sections it may invalidate."""
from __future__ import annotations

from docsentry.agents.doc_linker import _mentions, link_change_to_docs
from docsentry.core import retrieval

CHANGE = {
    "file": "calculator.py",
    "kind": "default_changed",
    "name": "divide",
    "detail": "`divide` default for `safe` changed: `True` → `False`",
}


def test_exact_name_match_uses_word_boundaries():
    """A substring test would link `divide` to a section about `divided` or
    `safe_divide`, producing a bogus issue."""
    assert _mentions("divide", "call divide(a, b) here")
    assert _mentions("divide", "`divide`")
    assert not _mentions("divide", "the numbers were divided")
    assert not _mentions("divide", "use safe_divide instead")


def test_links_change_to_the_right_section(local_repo):
    retrieval.reindex(str(local_repo))
    docs = link_change_to_docs(CHANGE, n=3)
    assert docs
    assert docs[0]["meta"]["file"] == "README.md"
    assert "divide" in docs[0]["content"]
    assert docs[0]["exact_match"] is True


def test_exact_match_outranks_lexical_score(monkeypatch):
    """An exact identifier mention must win even when another section scores
    far higher lexically."""
    monkeypatch.setattr(retrieval, "search", lambda q, n: [
        {"id": "1", "content": "lots of safe default words", "score": 99.0,
         "meta": {"file": "a.md"}},
        {"id": "2", "content": "mentions divide once", "score": 0.1,
         "meta": {"file": "b.md"}},
    ])
    docs = link_change_to_docs(CHANGE, n=2)
    assert docs[0]["id"] == "2"


def test_respects_n(local_repo):
    retrieval.reindex(str(local_repo))
    assert len(link_change_to_docs(CHANGE, n=1)) == 1


def test_no_docs_indexed_returns_empty(monkeypatch):
    monkeypatch.setattr(retrieval, "_index", None)
    assert link_change_to_docs(CHANGE) == []
