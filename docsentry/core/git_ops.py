"""Git access: obtaining the watched repo, and reading a commit's changes."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from git import GitCommandError, Repo

from docsentry.config import settings

log = logging.getLogger(__name__)


class GitOpsError(RuntimeError):
    """Something went wrong obtaining or reading the watched repository."""


def redact(text: str) -> str:
    """Strip credentials out of anything headed for a log or an API response."""
    return re.sub(r"(https://)[^@/\s]+(@)", r"\1***\2", str(text))


@dataclass
class FileChange:
    path: str
    change_type: str          # "added" | "modified" | "deleted"
    before: str = ""          # file content BEFORE the commit
    after: str = ""           # file content AFTER the commit


def _blob_text(blob) -> str:
    if blob is None:
        return ""
    try:
        return blob.data_stream.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001 - binary or unreadable blob is not fatal
        log.debug("unreadable blob %s: %s", getattr(blob, "path", "?"), e)
        return ""


def ensure_repo(fetch: bool = True) -> Path:
    """Return a local checkout of the watched repo, cloning it if necessary.

    A deployed instance has no sibling checkout to point at, so when
    local_repo_path is unset the repo is cloned into the data dir and reused
    across runs.
    """
    if settings.local_repo_path:
        path = Path(settings.local_repo_path).expanduser()
        if not (path / ".git").is_dir():
            raise GitOpsError(
                f"local_repo_path={path} is not a git repository. Unset it to let "
                "DocSentry clone target_repo itself."
            )
        if fetch:
            _try_fetch(Repo(path))
        return path.resolve()

    if not settings.target_repo:
        raise GitOpsError("target_repo is not set, so there is nothing to clone")

    dest = settings.repo_cache_path
    if (dest / ".git").is_dir():
        repo = Repo(dest)
        if fetch:
            # The token can rotate between deploys; refresh the URL each time.
            repo.remotes.origin.set_url(settings.clone_url)
            _try_fetch(repo)
            _reset_to_remote_head(repo)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            Repo.clone_from(settings.clone_url, dest)
        except GitCommandError as e:
            raise GitOpsError(f"clone of {settings.target_repo} failed: {redact(e)}") from e
    return dest.resolve()


def _try_fetch(repo: Repo) -> None:
    # A local-only checkout has no origin at all, which is normal when someone
    # points local_repo_path at a scratch repo.
    if "origin" not in {r.name for r in repo.remotes}:
        log.debug("no origin remote; nothing to fetch")
        return
    try:
        repo.remotes.origin.fetch(prune=True)
    except GitCommandError as e:
        # A stale checkout still beats failing the whole run: the commit we
        # need may already be present locally.
        log.warning("fetch failed, continuing with local state: %s", redact(e))


def _reset_to_remote_head(repo: Repo) -> None:
    try:
        branch = default_branch(repo)
        repo.git.checkout(branch)
        repo.git.reset("--hard", f"origin/{branch}")
    except GitCommandError as e:
        log.warning("could not reset to remote head: %s", redact(e))


def default_branch(repo: Repo) -> str:
    """The remote's default branch, falling back to the current one."""
    try:
        ref = repo.git.symbolic_ref("refs/remotes/origin/HEAD")
        return ref.rsplit("/", 1)[-1]
    except GitCommandError:
        pass
    for candidate in ("main", "master"):
        if candidate in {h.name for h in repo.heads}:
            return candidate
    try:
        return repo.active_branch.name
    except TypeError:  # detached HEAD
        return "main"


def get_commit_changes(repo_path: str | Path, commit_hash: str) -> list[FileChange]:
    """Every file touched by the commit, with its before/after contents."""
    try:
        repo = Repo(repo_path)
        commit = repo.commit(commit_hash)
    except Exception as e:  # noqa: BLE001 - bad hash / bad path both land here
        raise GitOpsError(f"cannot read commit {commit_hash!r}: {redact(e)}") from e

    # A root commit has no parent to diff against. v1 used commit.diff(None),
    # which compares against the *working tree* rather than the empty tree and
    # reports the inverse of what actually happened.
    if not commit.parents:
        return [
            FileChange(path=blob.path, change_type="added",
                       before="", after=_blob_text(blob))
            for blob in commit.tree.traverse()
            if blob.type == "blob"
        ]

    changes: list[FileChange] = []
    for d in commit.parents[0].diff(commit):
        if d.new_file:
            ctype, path = "added", d.b_path
        elif d.deleted_file:
            ctype, path = "deleted", d.a_path
        elif d.renamed_file:
            ctype, path = "modified", d.b_path
        else:
            ctype, path = "modified", d.b_path

        changes.append(FileChange(
            path=path,
            change_type=ctype,
            before="" if ctype == "added" else _blob_text(d.a_blob),
            after="" if ctype == "deleted" else _blob_text(d.b_blob),
        ))
    return changes


def latest_commit_hash(repo_path: str | Path) -> str:
    try:
        return Repo(repo_path).head.commit.hexsha
    except Exception as e:  # noqa: BLE001
        raise GitOpsError(f"cannot read HEAD of {repo_path}: {redact(e)}") from e


def commit_message(repo_path: str | Path, commit_hash: str) -> str:
    try:
        return Repo(repo_path).commit(commit_hash).message.strip().splitlines()[0]
    except Exception:  # noqa: BLE001 - cosmetic only
        return ""
