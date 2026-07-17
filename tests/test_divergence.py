from docsentry.core.vector_store import reindex
from docsentry.agents.doc_linker import link_change_to_docs
from docsentry.agents.divergence import check_divergence
from docsentry.config import settings


def test_catches_the_lie():
    reindex(settings.local_repo_path)
    change = {"file": "calculator.py", "kind": "params_changed",
              "name": "divide",
              "detail": "`divide` signature changed: (a, b, safe=True) → (a, b, safe=False)"}
    top_doc = link_change_to_docs(change)[0]
    verdict = check_divergence(change, top_doc)
    print(verdict)
    assert verdict["diverged"] is True
    assert verdict["confidence"] >= 0.7