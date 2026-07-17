from docsentry.core.vector_store import reindex
from docsentry.agents.doc_linker import link_change_to_docs
from docsentry.config import settings


def test_finds_divide_docs():
    count = reindex(settings.local_repo_path)
    assert count > 0
    change = {"file": "calculator.py", "kind": "params_changed",
              "name": "divide",
              "detail": "`divide` signature changed: (a, b, safe=True) → (a, b, safe=False)"}
    hits = link_change_to_docs(change)
    for h in hits:
        print(h["meta"]["file"], "|", h["meta"]["heading"], "| exact:", h["exact_match"])
    assert any("divide" in h["content"] for h in hits)