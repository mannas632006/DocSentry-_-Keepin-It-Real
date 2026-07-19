"""The ACT step (low confidence): open a 'Docs Lie' issue for human review."""
from __future__ import annotations

import logging
from typing import Any

from github import GithubException

from docsentry.config import settings
from docsentry.core import db
from docsentry.core.github_ops import GitHubError, ensure_label, get_repo

log = logging.getLogger(__name__)

DRY_RUN_URL = "dry-run://issue-not-opened"


def _confidence_note(confidence: float, reason: str) -> str:
    """Explain, accurately, why this became an issue rather than a fix PR.

    An issue is opened on two different paths — a below-threshold alert, and a
    high-confidence fix that could not be shipped. The body must not claim
    "below the threshold" for the second, or DocSentry is lying in exactly the
    way it exists to catch.
    """
    if reason:
        return reason
    if confidence >= settings.autofix_threshold:
        return ("at or above the auto-fix threshold, but the fix could not be "
                "opened as a PR — a human should apply it")
    return (f"below the {settings.autofix_threshold:.0%} auto-fix threshold, so "
            "this is a report rather than a pull request")


def _body(verdict: dict[str, Any], change: dict[str, Any], reason: str = "") -> str:
    fix = verdict.get("suggested_fix") or ""
    fix_block = f"""
**Suggested fix** — replaces `{verdict['doc_file']}` lines \
{verdict['doc_start_line']}-{verdict['doc_end_line']}:

````markdown
{fix}
````
""" if fix.strip() else "\n_No fix proposed._\n"

    return f"""## Possible documentation drift

**Code change:** `{change['detail']}`
**In file:** `{change['file']}`
**Doc section:** `{verdict['doc_file']}` → *{verdict['doc_heading']}*

**Suspected lie:** {verdict['mismatch']}

**Confidence:** {verdict['confidence']:.0%} \
({_confidence_note(verdict['confidence'], reason)})
{fix_block}
---
_Opened automatically by [DocSentry](https://github.com/mannas632006/DocSentry-_-Keepin-It-Real)._"""


def open_docs_lie_issue(verdict: dict[str, Any], change: dict[str, Any], *,
                        commit_hash: str = "", dry_run: bool | None = None,
                        reason: str = "") -> str:
    """File an issue, or return the existing one for identical drift.

    Returns the issue URL. v1 filed a fresh issue every run, so re-pushing the
    same commit accumulated duplicates.
    """
    dry_run = settings.dry_run if dry_run is None else dry_run

    key = db.alert_key(verdict["doc_file"], verdict["doc_heading"],
                       change["name"], change["detail"])
    existing = db.find_alert(key)
    if existing:
        log.info("reusing existing alert for %s: %s", verdict["doc_file"], existing)
        return existing

    if dry_run:
        return DRY_RUN_URL

    repo = get_repo()
    title = f"📄🔥 Docs Lie: {verdict['doc_file']} — {verdict['doc_heading']}"
    label = ensure_label(repo)
    try:
        issue = repo.create_issue(
            title=title,
            body=_body(verdict, change, reason),
            labels=[label] if label else [],
        )
    except GithubException as e:
        raise GitHubError(f"could not open issue: {e.data or e}") from e

    db.record_alert(key, issue.html_url, commit_hash)
    return issue.html_url
