"""The ACT step (high confidence): patch the doc, push a branch, open a PR."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from git import GitCommandError, Repo
from github import GithubException

from docsentry.config import settings
from docsentry.core import db
from docsentry.core.git_ops import default_branch, ensure_repo, redact
from docsentry.core.github_ops import GitHubError, get_repo

log = logging.getLogger(__name__)

DRY_RUN_URL = "dry-run://pr-not-opened"


class FixError(RuntimeError):
    """The suggested fix could not be applied."""


def render_fixed_doc(repo_path: str | Path, verdict: dict[str, Any]) -> str:
    """Return the doc file's full content with the diverged section replaced.

    Pure: reads the file but writes nothing, so the result can be inspected and
    tested without touching a checkout.
    """
    fix = (verdict.get("suggested_fix") or "").strip()
    if not fix:
        raise FixError("verdict carries no suggested_fix")

    doc_path = Path(repo_path) / verdict["doc_file"]
    if not doc_path.is_file():
        raise FixError(f"doc file not found: {verdict['doc_file']}")

    lines = doc_path.read_text(encoding="utf-8").splitlines()
    start = verdict["doc_start_line"] - 1
    end = verdict["doc_end_line"]

    # The line range comes from an index built before the fix was drafted. If
    # the file moved underneath us, splicing by stale offsets would corrupt it.
    if start < 0 or end > len(lines) or start >= end:
        raise FixError(
            f"section range {verdict['doc_start_line']}-{verdict['doc_end_line']} "
            f"is outside {verdict['doc_file']} ({len(lines)} lines)"
        )

    new_lines = lines[:start] + fix.splitlines() + lines[end:]
    new_text = "\n".join(new_lines) + "\n"
    # Compare line-wise, not byte-wise: new_text is always newline-terminated,
    # so a file without a trailing newline would otherwise look "changed" and
    # produce a PR whose only diff is that newline.
    if new_lines == lines:
        raise FixError("suggested fix is identical to the current content")
    return new_text


def apply_fix_locally(repo_path: str | Path, verdict: dict[str, Any]) -> str:
    """Write the fix to disk. Returns the new file content."""
    new_text = render_fixed_doc(repo_path, verdict)
    (Path(repo_path) / verdict["doc_file"]).write_text(new_text, encoding="utf-8")
    return new_text


def _branch_name(verdict: dict[str, Any], change: dict[str, Any]) -> str:
    """Stable per-drift branch name.

    v1 used a timestamp, so every re-run of the same drift opened another
    branch and another PR.
    """
    key = db.alert_key(verdict["doc_file"], verdict["doc_heading"],
                       change["name"], change["detail"])
    return f"docsentry/fix-{key[:12]}"


def _existing_pr_url(gh_repo, branch: str) -> str | None:
    try:
        owner = gh_repo.owner.login
        prs = gh_repo.get_pulls(state="open", head=f"{owner}:{branch}")
        for pr in prs:
            return pr.html_url
    except GithubException as e:
        log.warning("could not check for an existing PR: %s", e.data or e)
    return None


def _pr_body(verdict: dict[str, Any], change: dict[str, Any]) -> str:
    return f"""## Documentation drift detected

**Triggering change:** `{change['detail']}`
**In file:** `{change['file']}`

**The lie:** {verdict['mismatch']}

**Confidence:** {verdict['confidence']:.0%} \
(at or above the {settings.autofix_threshold:.0%} auto-fix threshold)

This fix was drafted automatically and then re-checked by the agent's own
verifier before this PR was opened. Review before merging.

---
_Opened automatically by [DocSentry](https://github.com/mannas632006/DocSentry-_-Keepin-It-Real)._"""


def open_fix_pr(verdict: dict[str, Any], change: dict[str, Any], *,
                dry_run: bool | None = None) -> str:
    """Branch, patch, push and open a PR. Returns the PR URL.

    The checkout is always restored to the base branch, even on failure. v1
    had no cleanup, so a mid-flight error stranded the working tree on a fix
    branch and broke every later run.
    """
    dry_run = settings.dry_run if dry_run is None else dry_run

    repo_path = ensure_repo(fetch=False)
    repo = Repo(repo_path)
    base = default_branch(repo)
    branch = _branch_name(verdict, change)

    # Validate the splice before creating any branch or making any API call.
    new_text = render_fixed_doc(repo_path, verdict)

    if dry_run:
        log.info("dry run: would open PR on %s for %s",
                 settings.target_repo, verdict["doc_file"])
        return DRY_RUN_URL

    gh_repo = get_repo()
    if existing := _existing_pr_url(gh_repo, branch):
        log.info("reusing open PR for %s: %s", branch, existing)
        return existing

    try:
        try:
            repo.git.checkout(base)
            repo.git.checkout("-B", branch)   # -B: reuse the branch if it exists
            (repo_path / verdict["doc_file"]).write_text(new_text, encoding="utf-8")
            repo.git.add(verdict["doc_file"])
            repo.index.commit(
                f"docs: fix drift in {verdict['doc_file']} ({verdict['doc_heading']})"
            )
            repo.git.push("--force-with-lease", "--set-upstream", "origin", branch)
        except GitCommandError as e:
            raise FixError(f"git failed while preparing the fix: {redact(e)}") from e

        try:
            pr = gh_repo.create_pull(
                title=f"🤖 DocSentry: fix documentation drift in {verdict['doc_file']}",
                body=_pr_body(verdict, change),
                head=branch,
                base=base,
            )
        except GithubException as e:
            raise GitHubError(f"could not open PR: {e.data or e}") from e
        return pr.html_url

    finally:
        _restore(repo, base, branch)


def _restore(repo: Repo, base: str, branch: str) -> None:
    """Return the checkout to a clean base branch, whatever happened."""
    try:
        repo.git.reset("--hard")
        repo.git.checkout(base)
        if branch in {h.name for h in repo.heads}:
            repo.delete_head(branch, force=True)
    except GitCommandError as e:
        log.warning("could not restore checkout to %s: %s", base, redact(e))
