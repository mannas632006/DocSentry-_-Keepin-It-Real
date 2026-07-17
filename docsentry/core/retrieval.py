"""Doc-section retrieval, with a pluggable backend.

v1 used ChromaDB + sentence-transformers. That works, but it drags in PyTorch
(~800MB installed), which no free hosting tier will accept, and it is a poor
fit for the actual query: the strongest signal that a doc section describes
`divide` is the literal token "divide" appearing in it. BM25 scores exact
lexical overlap directly, in pure Python, with no model to download.

Chroma remains available behind the [chroma] extra for anyone who wants dense
semantic matching locally.

The index is rebuilt in memory on each run. A repo's markdown is a handful of
kilobytes, so indexing costs milliseconds and there is nothing to persist or
invalidate.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from docsentry.config import settings
from docsentry.core.parser import collect_doc_sections

# Identifiers and bare numbers. Punctuation and markdown syntax are noise.
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_WORD_PART_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+")

# Words too common in prose to carry signal. Deliberately limited to English
# function words: domain terms like "default", "returns" or "raises" are
# exactly the language a doc uses to state the behaviour a change just broke,
# so they must stay searchable.
_STOPWORDS = frozenset("""
a an the and or but if then than that this these those is are was were be been
being to of in on at by for with from as it its into about over under not no
you your we our they their he she i me my will would can could should may might
do does did done have has had
""".split())


def _split_identifier(ident: str) -> list[str]:
    """safe_divide -> [safe, divide];  parseJSON -> [parse, JSON]."""
    parts: list[str] = []
    for chunk in ident.split("_"):
        if chunk:
            parts.extend(_WORD_PART_RE.findall(chunk))
    return parts


def tokenize(text: str) -> list[str]:
    """Lowercase tokens, plus the sub-words of any compound identifier.

    Emitting both `safe_divide` and its parts means a doc that says "divide"
    still matches a change to `safe_divide`, without a semantic model.
    """
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        low = raw.lower()
        if low not in _STOPWORDS:
            tokens.append(low)
        parts = _split_identifier(raw)
        if len(parts) > 1:
            tokens.extend(p.lower() for p in parts if p.lower() not in _STOPWORDS)
    return tokens


@dataclass
class _Indexed:
    id: str
    content: str
    meta: dict[str, Any]
    tokens: list[str] = field(default_factory=list)
    freqs: Counter = field(default_factory=Counter)


class BM25Index:
    """Okapi BM25. k1 and b are the standard defaults from the literature."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: list[_Indexed] = []
        self._df: Counter = Counter()
        self._avg_len: float = 0.0

    def __len__(self) -> int:
        return len(self._docs)

    def add(self, docs: list[_Indexed]) -> None:
        self._docs = docs
        self._df = Counter()
        for d in docs:
            d.tokens = tokenize(d.content)
            d.freqs = Counter(d.tokens)
            for term in d.freqs:
                self._df[term] += 1
        total = sum(len(d.tokens) for d in docs)
        self._avg_len = (total / len(docs)) if docs else 0.0

    def _idf(self, term: str) -> float:
        n = len(self._docs)
        df = self._df.get(term, 0)
        # +1 inside the log keeps the idf non-negative for terms in most docs.
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, n: int = 5) -> list[dict[str, Any]]:
        if not self._docs:
            return []
        q_terms = tokenize(query)
        scored: list[tuple[float, _Indexed]] = []
        for d in self._docs:
            dl = len(d.tokens) or 1
            score = 0.0
            for term in q_terms:
                f = d.freqs.get(term, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self._avg_len or 1))
                score += self._idf(term) * (f * (self.k1 + 1)) / denom
            scored.append((score, d))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {"id": d.id, "content": d.content, "meta": d.meta, "score": round(s, 4)}
            for s, d in scored[:n]
            if s > 0
        ]


class _ChromaIndex:
    """Dense-vector backend. Requires the [chroma] extra."""

    def __init__(self) -> None:
        try:
            import chromadb  # noqa: PLC0415 - optional dependency, import on use
        except ImportError as e:  # pragma: no cover - depends on install extras
            raise RuntimeError(
                "retrieval_backend='chroma' requires the extra: "
                "pip install 'docsentry[chroma]'"
            ) from e
        self._chromadb = chromadb
        self._client = chromadb.EphemeralClient()
        self._col = None

    def __len__(self) -> int:
        return self._col.count() if self._col else 0

    def add(self, docs: list[_Indexed]) -> None:
        try:
            self._client.delete_collection("doc_sections")
        except Exception:  # noqa: BLE001 - absent collection is not an error
            pass
        self._col = self._client.get_or_create_collection("doc_sections")
        if not docs:
            return
        self._col.add(
            ids=[d.id for d in docs],
            documents=[d.content for d in docs],
            metadatas=[d.meta for d in docs],
        )

    def search(self, query: str, n: int = 5) -> list[dict[str, Any]]:
        if not self._col or self._col.count() == 0:
            return []
        res = self._col.query(query_texts=[query], n_results=min(n, self._col.count()))
        hits = []
        for i in range(len(res["ids"][0])):
            dist = res["distances"][0][i]
            hits.append({
                "id": res["ids"][0][i],
                "content": res["documents"][0][i],
                "meta": res["metadatas"][0][i],
                # Invert distance so every backend agrees that higher = better.
                "score": round(1.0 / (1.0 + dist), 4),
            })
        return hits


_index: BM25Index | _ChromaIndex | None = None


def _new_index() -> BM25Index | _ChromaIndex:
    if settings.retrieval_backend == "chroma":
        return _ChromaIndex()
    return BM25Index()


def reindex(repo_path: str) -> int:
    """Rebuild the doc index from every markdown file in the repo.

    Returns the number of indexed sections.
    """
    global _index
    sections = collect_doc_sections(repo_path)
    docs = [
        _Indexed(
            id=s.id,
            # Index the heading alongside the body: headings carry the
            # strongest naming signal ("### divide(a, b, safe=True)").
            content=f"{s.heading}\n{s.content}",
            meta={
                "file": s.file,
                "heading": s.heading,
                "start_line": s.start_line,
                "end_line": s.end_line,
            },
        )
        for s in sections
    ]
    _index = _new_index()
    _index.add(docs)
    return len(docs)


def search(query: str, n: int = 5) -> list[dict[str, Any]]:
    """Top-n doc sections for a query. Empty if reindex() has not run."""
    if _index is None:
        return []
    return _index.search(query, n=n)


def index_size() -> int:
    return len(_index) if _index is not None else 0
