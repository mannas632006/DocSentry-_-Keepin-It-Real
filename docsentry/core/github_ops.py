"""Shared GitHub client access."""
from __future__ import annotations

import logging
from functools import lru_cache

from github import Github, GithubException
from github.Repository import Repository

from docsentry.config import settings

log = logging.getLogger(__name__)

LABEL = "docs-lie"
LABEL_COLOR = "d73a4a"


class GitHubError(RuntimeError):
    """A GitHub API call failed."""


@lru_cache(maxsize=None)
def _client(token: str) -> Github:
    return Github(token, timeout=30)


def get_repo() -> Repository:
    """The watched repository. v1 built a fresh client on every call."""
    if not settings.github_token:
        raise GitHubError("github_token is not set")
    if not settings.target_repo:
        raise GitHubError("target_repo is not set")
    try:
        return _client(settings.github_token).get_repo(settings.target_repo)
    except GithubException as e:
        raise GitHubError(f"cannot access {settings.target_repo}: {e.data or e}") from e


def ensure_label(repo: Repository) -> str | None:
    """Create the docs-lie label if absent, and report whether it is usable.

    v1 dropped labels entirely because posting a non-existent label 422s.
    Creating it first keeps the labelling without the failure.
    """
    try:
        repo.get_label(LABEL)
        return LABEL
    except GithubException:
        pass
    try:
        repo.create_label(name=LABEL, color=LABEL_COLOR,
                          description="Documentation contradicted by code")
        return LABEL
    except GithubException as e:
        # Most likely a token without Issues:write. Not worth failing over.
        log.warning("could not create %r label: %s", LABEL, e.data or e)
        return None


def get_issue_body(number: int) -> str:
    """The body of one issue, for reading back an embedded fix payload."""
    try:
        return get_repo().get_issue(number).body or ""
    except GithubException as e:
        raise GitHubError(f"cannot read issue #{number}: {e.data or e}") from e


def comment_on_issue(number: int, body: str) -> None:
    try:
        get_repo().get_issue(number).create_comment(body)
    except GithubException as e:
        raise GitHubError(f"cannot comment on issue #{number}: {e.data or e}") from e


def close_issue(number: int, comment: str = "") -> None:
    try:
        issue = get_repo().get_issue(number)
        if comment:
            issue.create_comment(comment)
        issue.edit(state="closed")
    except GithubException as e:
        raise GitHubError(f"cannot close issue #{number}: {e.data or e}") from e
