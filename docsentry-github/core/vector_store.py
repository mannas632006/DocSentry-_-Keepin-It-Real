"""ChromaDB wrapper: index doc sections, query by semantic change."""
import chromadb
from chromadb.utils import embedding_functions

from docsentry.core.parser import DocSection, collect_doc_sections

_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)
_client = chromadb.PersistentClient(path="./chroma_db")


def get_collection():
    return _client.get_or_create_collection("doc_sections", embedding_function=_ef)


def reindex(repo_path: str) -> int:
    """Wipe and rebuild the doc index. Returns section count."""
    try:
        _client.delete_collection("doc_sections")
    except Exception:
        pass
    col = get_collection()
    sections = collect_doc_sections(repo_path)
    if not sections:
        return 0
    col.add(
        ids=[s.id for s in sections],
        documents=[f"{s.heading}\n{s.content}" for s in sections],
        metadatas=[{"file": s.file, "heading": s.heading,
                    "start_line": s.start_line, "end_line": s.end_line}
                   for s in sections],
    )
    return len(sections)


def search(query: str, n: int = 5) -> list[dict]:
    col = get_collection()
    res = col.query(query_texts=[query], n_results=min(n, max(col.count(), 1)))
    hits = []
    for i in range(len(res["ids"][0])):
        hits.append({
            "id": res["ids"][0][i],
            "content": res["documents"][0][i],
            "meta": res["metadatas"][0][i],
            "distance": res["distances"][0][i],
        })
    return hits