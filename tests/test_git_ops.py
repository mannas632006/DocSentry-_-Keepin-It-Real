"""Reading commits out of a real (temporary) git repository."""
from __future__ import annotations

import pytest
from git import Actor, Repo

from docsentry.core.git_ops import (
    GitOpsError,
    commit_message,
    default_branch,
    ensure_repo,
    get_commit_changes,
    latest_commit_hash,
    redact,
)

AUTHOR = Actor("T", "t@example.com")


def test_reads_before_and_after_contents(repo):
    changes = get_commit_changes(repo, latest_commit_hash(repo))
    calc = next(c for c in changes if c.path == "calculator.py")
    assert calc.change_type == "modified"
    assert "safe=True" in calc.before
    assert "safe=False" in calc.after


def test_root_commit_reports_files_as_added(repo):
    """v1 used commit.diff(None) for the root commit, which compares against
    the working tree instead of the empty tree and inverts the result."""
    r = Repo(repo)
    root = list(r.iter_commits())[-1]
    changes = get_commit_changes(repo, root.hexsha)

    assert {c.path for c in changes} == {"calculator.py", "README.md"}
    assert all(c.change_type == "added" for c in changes)
    assert all(c.before == "" for c in changes)
    calc = next(c for c in changes if c.path == "calculator.py")
    assert "def divide" in calc.after


def test_added_file(repo):
    r = Repo(repo)
    (repo / "extra.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    r.index.add(["extra.py"])
    c = r.index.commit("add helper", author=AUTHOR, committer=AUTHOR)

    change = next(x for x in get_commit_changes(repo, c.hexsha) if x.path == "extra.py")
    assert change.change_type == "added"
    assert change.before == ""
    assert "helper" in change.after


def test_deleted_file(repo):
    r = Repo(repo)
    r.index.remove(["calculator.py"], working_tree=True)
    c = r.index.commit("remove calc", author=AUTHOR, committer=AUTHOR)

    change = next(x for x in get_commit_changes(repo, c.hexsha)
                  if x.path == "calculator.py")
    assert change.change_type == "deleted"
    assert "def divide" in change.before
    assert change.after == ""


def test_bad_commit_hash_raises_gitopserror(repo):
    with pytest.raises(GitOpsError, match="cannot read commit"):
        get_commit_changes(repo, "not-a-real-sha")


def test_commit_message_first_line(repo):
    assert commit_message(repo, latest_commit_hash(repo)) == \
        "Change divide default to unsafe"


def test_commit_message_on_bad_hash_is_empty(repo):
    assert commit_message(repo, "nope") == ""


def test_default_branch(repo):
    assert default_branch(Repo(repo)) == "main"


def test_ensure_repo_uses_local_path(local_repo):
    assert ensure_repo(fetch=False) == local_repo.resolve()


def test_ensure_repo_with_fetch_on_a_remoteless_repo(local_repo):
    """A local-only checkout has no origin. Reaching for repo.remotes.origin
    raises AttributeError rather than GitCommandError, so it slipped past the
    error handling and killed the run."""
    assert ensure_repo(fetch=True) == local_repo.resolve()


def test_ensure_repo_rejects_non_repo(tmp_path, monkeypatch):
    from docsentry.config import settings
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    monkeypatch.setattr(settings, "local_repo_path", str(plain))
    with pytest.raises(GitOpsError, match="not a git repository"):
        ensure_repo(fetch=False)


def test_ensure_repo_needs_a_target(monkeypatch):
    from docsentry.config import settings
    monkeypatch.setattr(settings, "local_repo_path", "")
    monkeypatch.setattr(settings, "target_repo", "")
    with pytest.raises(GitOpsError, match="nothing to clone"):
        ensure_repo(fetch=False)


def test_redact_strips_token_from_urls():
    """Clone URLs embed the PAT; they must never reach a log or an API reply."""
    url = "https://x-access-token:ghp_SECRET123@github.com/acme/repo.git"
    out = redact(f"fatal: could not read from {url}")
    assert "ghp_SECRET123" not in out
    assert "***" in out
    assert "github.com/acme/repo.git" in out


def test_redact_leaves_clean_text_alone():
    assert redact("https://github.com/acme/repo") == "https://github.com/acme/repo"
