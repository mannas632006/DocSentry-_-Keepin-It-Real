"""Shared fixtures.

Everything here is hermetic: no network, no Ollama, no sibling checkout. The
v1 suite required all three, which is why it could not run in CI — or, once
the testbed repo was gone, at all.
"""
from __future__ import annotations

import pytest
from git import Actor, Repo

from docsentry.config import settings

CALCULATOR_V1 = '''"""A small calculator."""


def add(a, b):
    """Add two numbers."""
    return a + b


def divide(a, b, safe=True):
    """Divide a by b. When safe is True, dividing by zero returns None."""
    if safe and b == 0:
        return None
    return a / b
'''

# The canonical demo change: the default flips, the code still works, the docs
# silently become false.
CALCULATOR_V2 = CALCULATOR_V1.replace("def divide(a, b, safe=True):",
                                      "def divide(a, b, safe=False):")

README_V1 = """# Calculator

A tiny calculator library.

## add

`add(a, b)` returns the sum of two numbers.

## divide

`divide(a, b, safe=True)` divides a by b.

By default `safe` is **True**, so dividing by zero returns `None` rather than
raising. Pass `safe=False` to get the raw ZeroDivisionError.

```python
# this comment must not be parsed as a heading
divide(1, 0)   # -> None
```

## Notes

Nothing else to say.
"""


@pytest.fixture
def repo(tmp_path):
    """A real git repo with two commits: docs true, then docs lying.

    Returns the repo path. HEAD is the commit that flips the default.
    """
    path = tmp_path / "testbed"
    path.mkdir()
    r = Repo.init(path, initial_branch="main")
    author = Actor("DocSentry Tests", "tests@example.com")

    (path / "calculator.py").write_text(CALCULATOR_V1, encoding="utf-8")
    (path / "README.md").write_text(README_V1, encoding="utf-8")
    r.index.add(["calculator.py", "README.md"])
    r.index.commit("Initial calculator", author=author, committer=author)

    (path / "calculator.py").write_text(CALCULATOR_V2, encoding="utf-8")
    r.index.add(["calculator.py"])
    r.index.commit("Change divide default to unsafe", author=author, committer=author)

    return path


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Point every test at a throwaway data dir and a known config.

    autouse so no test can accidentally touch the developer's real database.
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "target_repo", "acme/testbed")
    monkeypatch.setattr(settings, "github_token", "test-token")
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "retrieval_backend", "bm25")
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "max_docs_per_change", 1)
    monkeypatch.setattr(settings, "autofix_threshold", 0.85)
    monkeypatch.setattr(settings, "alert_threshold", 0.50)
    monkeypatch.setattr(settings, "admin_token", "")
    # Default the tests to autonomous mode; the approval-flow tests opt back in
    # explicitly. (The product default is require_approval=True.)
    monkeypatch.setattr(settings, "require_approval", False)
    yield settings


@pytest.fixture
def local_repo(repo, monkeypatch):
    """Make the watched repo the temp checkout, so nothing gets cloned."""
    monkeypatch.setattr(settings, "local_repo_path", str(repo))
    return repo


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the model with a scripted reply.

    Usage:
        fake_llm.reply = {"diverged": True, "confidence": 0.9, ...}
        fake_llm.replies = [verdict1, verdict2]   # consumed in order
    """
    class Fake:
        def __init__(self):
            self.reply: dict | None = None
            self.replies: list[dict] = []
            self.calls: list[tuple[str, str]] = []
            self.error: Exception | None = None

        def __call__(self, system: str, user: str, **kw):
            self.calls.append((system, user))
            if self.error:
                raise self.error
            if self.replies:
                return self.replies.pop(0)
            return self.reply or {
                "diverged": False, "confidence": 0.0,
                "mismatch": "", "suggested_fix": "",
            }

    fake = Fake()
    # divergence imports the symbol directly, so patch it where it is used.
    monkeypatch.setattr("docsentry.agents.divergence.complete_json", fake)
    return fake
