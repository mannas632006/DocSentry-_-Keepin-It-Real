"""Link a semantic code change to the doc sections it may invalidate."""
from docsentry.core import vector_store


def link_change_to_docs(change: dict, n: int = 4) -> list[dict]:
    """change = one SemanticChange dict from the ChangeReport."""
    query = f"{change['name']} {change['detail']}"
    hits = vector_store.search(query, n=n)

    # keyword boost: exact function-name mention outranks pure similarity
    for h in hits:
        h["exact_match"] = change["name"] in h["content"]
    hits.sort(key=lambda h: (not h["exact_match"], h["distance"]))
    return hits