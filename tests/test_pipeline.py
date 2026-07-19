"""The full PERCEIVE -> REASON -> ACT -> VERIFY loop, with side effects faked."""
from __future__ import annotations

import pytest

from docsentry.core.git_ops import latest_commit_hash
from docsentry.pipeline import RunOptions, run_pipeline

DIVERGED = {
    "diverged": True,
    "confidence": 0.95,
    "mismatch": "The doc says safe defaults to True; it is now False.",
    "suggested_fix": "## divide\n\n`divide(a, b, safe=False)` divides a by b.\n\n"
                     "By default `safe` is **False**.",
}
CLEAN = {"diverged": False, "confidence": 0.9, "mismatch": "", "suggested_fix": ""}


@pytest.fixture
def no_github(monkeypatch):
    """Record what the agent would send to GitHub instead of sending it."""
    calls = {"issues": [], "prs": []}

    def fake_issue(verdict, change, *, commit_hash="", dry_run=None, reason=""):
        calls["issues"].append((verdict, change, reason))
        return "https://github.com/acme/testbed/issues/1"

    def fake_pr(verdict, change, *, dry_run=None):
        calls["prs"].append((verdict, change))
        return "https://github.com/acme/testbed/pull/2"

    monkeypatch.setattr("docsentry.pipeline.open_docs_lie_issue", fake_issue)
    monkeypatch.setattr("docsentry.pipeline.open_fix_pr", fake_pr)
    return calls


@pytest.fixture
def head(local_repo):
    return latest_commit_hash(local_repo)


def test_high_confidence_opens_a_pr(local_repo, head, fake_llm, no_github):
    # First call: the divergence verdict. Second: the verifier's re-check.
    fake_llm.replies = [DIVERGED, CLEAN]
    results = run_pipeline(head)

    statuses = [r["status"] for r in results]
    assert "auto_fixed" in statuses
    assert len(no_github["prs"]) == 1
    assert not no_github["issues"]

    fixed = next(r for r in results if r["status"] == "auto_fixed")
    assert fixed["url"].endswith("/pull/2")
    assert fixed["confidence"] == 0.95
    assert fixed["doc"]["file"] == "README.md"


def test_failed_verification_escalates_to_an_issue(local_repo, head, fake_llm, no_github):
    """If the re-check still finds a lie, the fix must not ship."""
    fake_llm.replies = [DIVERGED, DIVERGED]
    results = run_pipeline(head)

    assert [r["status"] for r in results] == ["fix_failed_verification"]
    assert not no_github["prs"]
    assert len(no_github["issues"]) == 1
    assert "still diverges" in results[0]["mismatch"]


def test_mid_confidence_opens_an_issue(local_repo, head, fake_llm, no_github):
    fake_llm.reply = {**DIVERGED, "confidence": 0.6}
    results = run_pipeline(head)

    assert [r["status"] for r in results] == ["alerted"]
    assert len(no_github["issues"]) == 1
    assert not no_github["prs"]


def test_low_confidence_is_skipped(local_repo, head, fake_llm, no_github):
    fake_llm.reply = {**DIVERGED, "confidence": 0.1}
    results = run_pipeline(head)

    assert [r["status"] for r in results] == ["low_confidence_skip"]
    assert not no_github["issues"] and not no_github["prs"]


def test_clean_verdict_reports_clean(local_repo, head, fake_llm, no_github):
    fake_llm.reply = CLEAN
    results = run_pipeline(head)

    assert [r["status"] for r in results] == ["clean"]
    assert not no_github["issues"] and not no_github["prs"]


def test_one_change_yields_one_finding_by_default(local_repo, head, fake_llm, no_github):
    """v1 judged the top 3 doc sections and filed an issue for each, so one
    flipped default produced three near-duplicate issues."""
    fake_llm.reply = {**DIVERGED, "confidence": 0.6}
    results = run_pipeline(head)
    assert len(no_github["issues"]) == 1
    assert len(results) == 1


def test_irrelevant_sections_are_never_judged(local_repo, head, fake_llm, no_github):
    """Even asked for three doc sections, only the ones that actually mention
    `divide` are judged. v1's dense retrieval always returned n sections
    whether or not they were related, and filed an issue for each."""
    fake_llm.reply = {**DIVERGED, "confidence": 0.6}
    results = run_pipeline(head, RunOptions(max_docs_per_change=3))

    assert len(results) == 1
    assert results[0]["doc"]["heading"] == "divide"


def test_max_docs_override_widens_the_search(local_repo, head, fake_llm, no_github):
    """A second doc that also documents divide should be judged too."""
    from git import Actor, Repo
    (local_repo / "GUIDE.md").write_text(
        "# Guide\n\n## Dividing\n\nCall `divide(a, b, safe=True)`; safe is True "
        "by default so division by zero returns None.\n",
        encoding="utf-8")
    r = Repo(local_repo)
    r.index.add(["GUIDE.md"])
    author = Actor("T", "t@example.com")
    r.index.commit("add guide", author=author, committer=author)

    fake_llm.reply = {**DIVERGED, "confidence": 0.6}
    results = run_pipeline(head, RunOptions(max_docs_per_change=3))

    assert len(results) == 2
    assert {r_["doc"]["file"] for r_ in results} == {"README.md", "GUIDE.md"}


def test_threshold_override_changes_routing(local_repo, head, fake_llm, no_github):
    """Same verdict, different threshold: alert instead of auto-fix."""
    fake_llm.replies = [DIVERGED, CLEAN]
    results = run_pipeline(head, RunOptions(autofix_threshold=0.99))
    assert [r["status"] for r in results] == ["alerted"]


def test_dry_run_opens_nothing(local_repo, head, fake_llm, monkeypatch):
    """dry_run must reach the real act functions and be honoured there, so it
    is deliberately not stubbed out here."""
    fake_llm.replies = [DIVERGED, CLEAN]
    results = run_pipeline(head, RunOptions(dry_run=True))

    assert [r["status"] for r in results] == ["auto_fixed"]
    assert results[0]["url"].startswith("dry-run://")


def test_docs_only_commit_reports_no_semantic_changes(local_repo, fake_llm, no_github):
    from git import Actor, Repo
    r = Repo(local_repo)
    (local_repo / "README.md").write_text("# Calculator\n\nreworded.\n", encoding="utf-8")
    r.index.add(["README.md"])
    author = Actor("T", "t@example.com")
    c = r.index.commit("docs only", author=author, committer=author)

    results = run_pipeline(c.hexsha)
    assert [r_["status"] for r_ in results] == ["no_semantic_changes"]
    assert fake_llm.calls == []


def test_llm_failure_does_not_abort_the_run(local_repo, head, fake_llm, no_github):
    from docsentry.llm import LLMError
    fake_llm.error = LLMError("groq is down")
    results = run_pipeline(head)
    # An unreachable model yields a non-diverged verdict, not an exception.
    assert results
    assert all(r["status"] in ("clean", "low_confidence_skip") for r in results)


def test_repo_with_no_markdown(tmp_path, fake_llm, monkeypatch):
    from git import Actor, Repo
    from docsentry.config import settings

    path = tmp_path / "nodocs"
    path.mkdir()
    r = Repo.init(path, initial_branch="main")
    author = Actor("T", "t@example.com")
    (path / "calculator.py").write_text("def divide(a, b, safe=True):\n    pass\n",
                                        encoding="utf-8")
    r.index.add(["calculator.py"])
    r.index.commit("one", author=author, committer=author)
    (path / "calculator.py").write_text("def divide(a, b, safe=False):\n    pass\n",
                                        encoding="utf-8")
    r.index.add(["calculator.py"])
    c = r.index.commit("two", author=author, committer=author)
    monkeypatch.setattr(settings, "local_repo_path", str(path))

    results = run_pipeline(c.hexsha)
    assert [x["status"] for x in results] == ["no_docs_indexed"]


def test_run_options_resolve_from_settings(isolated_settings):
    resolved = RunOptions().resolved()
    assert resolved["autofix_threshold"] == isolated_settings.autofix_threshold
    assert resolved["dry_run"] is False

    override = RunOptions(dry_run=True, alert_threshold=0.1).resolved()
    assert override["dry_run"] is True
    assert override["alert_threshold"] == 0.1


def test_dry_run_false_overrides_a_dry_run_environment(isolated_settings, monkeypatch):
    """dry_run=False must force acting even when the environment sets it true —
    render.yaml deliberately ships dry_run=true, so without an off switch a
    deployed instance could never open anything."""
    monkeypatch.setattr(isolated_settings, "dry_run", True)
    assert RunOptions().resolved()["dry_run"] is True          # inherits
    assert RunOptions(dry_run=False).resolved()["dry_run"] is False  # forces off
