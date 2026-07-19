"""The ACT step: open a 'Docs Lie' issue for human review.

Two shapes of issue:
- a plain alert (open_docs_lie_issue) — a report, no one-click fix; and
- a review issue (open_review_issue) — carries the exact fix DocSentry can
  apply, plus the `/docsentry apply` approval command. This is the default
  path when require_approval is on: nothing is applied until a human approves.
"""
from __future__ import annotations

import logging
from typing import Any

from github import GithubException

from docsentry.agents.review import encode_fix
from docsentry.config import settings
from docsentry.core import db
from docsentry.core.github_ops import GitHubError, ensure_label, get_repo

log = logging.getLogger(__name__)

DRY_RUN_URL = "dry-run://issue-not-opened"
REVIEW_DRY_RUN_URL = "dry-run://review-not-opened"


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


def _review_body(verdict: dict[str, Any], change: dict[str, Any],
                 commit_hash: str, verified: str = "") -> str:
    fix = verdict.get("suggested_fix") or ""
    verified_line = f"\n**Self-check:** {verified}\n" if verified else ""
    return f"""## Documentation drift — awaiting your decision

DocSentry found a code change that makes the docs below false. It has **not**
changed anything. Here is the problem and the fix it can apply for you.

**What changed:** `{change['detail']}`
**In file:** `{change['file']}`
**Doc section:** `{verdict['doc_file']}` → *{verdict['doc_heading']}* \
(lines {verdict['doc_start_line']}-{verdict['doc_end_line']})

**Why it's now wrong:** {verdict['mismatch']}

**Confidence:** {verdict['confidence']:.0%}
{verified_line}
### The fix DocSentry can apply

It would replace that section with:

````markdown
{fix or '(no fix could be drafted — please edit the docs by hand)'}
````

### Your options

- **Apply it** — comment **`/docsentry apply`** and DocSentry opens a pull
  request with exactly the change above, for you to merge.
- **Not this** — comment **`/docsentry dismiss`** to close this, or just edit
  the docs yourself. Nothing happens until you say so.

{encode_fix(verdict, change, commit_hash)}
---
_Opened automatically by [DocSentry](https://github.com/mannas632006/DocSentry-_-Keepin-It-Real). It will not act without your approval._"""


def open_review_issue(verdict: dict[str, Any], change: dict[str, Any], *,
                      commit_hash: str = "", dry_run: bool | None = None,
                      verified: str = "") -> str:
    """Open a review issue carrying the exact fix, for approval-gated applying.

    De-duplicated like a plain alert, so re-pushing the same drift reuses the
    open review issue rather than filing another.
    """
    dry_run = settings.dry_run if dry_run is None else dry_run

    key = db.alert_key(verdict["doc_file"], verdict["doc_heading"],
                       change["name"], change["detail"])
    existing = db.find_alert(key)
    if existing:
        log.info("reusing existing review issue for %s: %s",
                 verdict["doc_file"], existing)
        return existing

    if dry_run:
        return REVIEW_DRY_RUN_URL

    repo = get_repo()
    title = f"📄🔥 Docs Lie: {verdict['doc_file']} — {verdict['doc_heading']}"
    label = ensure_label(repo)
    try:
        issue = repo.create_issue(
            title=title,
            body=_review_body(verdict, change, commit_hash, verified),
            labels=[label] if label else [],
        )
    except GithubException as e:
        raise GitHubError(f"could not open review issue: {e.data or e}") from e

    db.record_alert(key, issue.html_url, commit_hash)
    return issue.html_url
