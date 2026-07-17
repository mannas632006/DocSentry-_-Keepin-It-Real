"""BM25 retrieval and tokenization."""
from __future__ import annotations

import pytest

from docsentry.core import retrieval
from docsentry.core.retrieval import BM25Index, _Indexed, tokenize


def _doc(doc_id, content, **meta):
    return _Indexed(id=doc_id, content=content, meta=meta or {"file": "d.md"})


def test_tokenize_splits_snake_case():
    toks = tokenize("safe_divide")
    assert "safe_divide" in toks
    # The sub-words matter: a doc saying "divide" should still match a change
    # to safe_divide without a semantic model.
    assert "divide" in toks


def test_tokenize_splits_camel_case():
    toks = tokenize("parseJSON")
    assert "parse" in toks
    assert "json" in toks


def test_tokenize_drops_stopwords():
    assert "the" not in tokenize("the divide")
    assert "divide" in tokenize("the divide")


def test_tokenize_ignores_punctuation():
    assert tokenize("divide(a, b)") == tokenize("divide a b")


def test_ranks_the_section_that_names_the_function_first():
    idx = BM25Index()
    idx.add([
        _doc("1", "add\n`add(a, b)` returns the sum."),
        _doc("2", "divide\n`divide(a, b, safe=True)` divides a by b."),
        _doc("3", "notes\nNothing else to say."),
    ])
    hits = idx.search("divide safe default changed", n=3)
    assert hits[0]["id"] == "2"


def test_zero_score_docs_excluded():
    idx = BM25Index()
    idx.add([_doc("1", "completely unrelated prose")])
    assert idx.search("divide", n=5) == []


def test_empty_index_returns_empty():
    assert BM25Index().search("anything") == []


def test_search_before_reindex_is_empty(monkeypatch):
    monkeypatch.setattr(retrieval, "_index", None)
    assert retrieval.search("divide") == []


def test_reindex_over_repo(local_repo):
    n = retrieval.reindex(str(local_repo))
    assert n >= 3          # intro/add/divide/notes
    hits = retrieval.search("divide safe", n=3)
    assert hits
    assert any("divide" in h["content"] for h in hits)
    assert retrieval.index_size() == n


def test_reindex_is_idempotent(local_repo):
    first = retrieval.reindex(str(local_repo))
    second = retrieval.reindex(str(local_repo))
    assert first == second


def test_heading_is_indexed_with_body(local_repo):
    retrieval.reindex(str(local_repo))
    hits = retrieval.search("divide", n=5)
    top = hits[0]
    assert top["meta"]["heading"]
    assert top["meta"]["file"] == "README.md"
    assert {"start_line", "end_line"} <= set(top["meta"])


def test_scores_are_descending(local_repo):
    retrieval.reindex(str(local_repo))
    scores = [h["score"] for h in retrieval.search("divide safe zero", n=5)]
    assert scores == sorted(scores, reverse=True)


def test_chroma_backend_reports_missing_extra(monkeypatch):
    """Selecting chroma without the extra installed must say so plainly."""
    pytest.importorskip("builtins")  # always runs; guard is below
    import sys
    monkeypatch.setitem(sys.modules, "chromadb", None)
    from docsentry.config import settings
    monkeypatch.setattr(settings, "retrieval_backend", "chroma")
    with pytest.raises(RuntimeError, match="chroma"):
        retrieval._new_index()
