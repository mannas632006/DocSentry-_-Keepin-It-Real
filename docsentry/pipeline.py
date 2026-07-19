"""PERCEIVE → REASON → ACT → VERIFY, end to end for one commit."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from docsentry.agents.alerter import open_docs_lie_issue
from docsentry.agents.auto_fixer import FixError, open_fix_pr
from docsentry.agents.diff_analyzer import analyze_commit
from docsentry.agents.divergence import check_divergence
from docsentry.agents.doc_linker import link_change_to_docs
from docsentry.agents.verifier import verify_fix
from docsentry.config import settings
from docsentry.core import retrieval
from docsentry.core.git_ops import GitOpsError, ensure_repo, get_commit_changes
from docsentry.core.github_ops import GitHubError

log = logging.getLogger(__name__)


@dataclass
class RunOptions:
    """Per-run overrides. Unset fields fall back to the global settings.

    Lets the dashboard trigger a one-off run at a different threshold, or in
    dry-run mode, without mutating server config.
    """
    dry_run: bool | None = None
    autofix_threshold: float | None = None
    alert_threshold: float | None = None
    max_docs_per_change: int | None = None

    def resolved(self) -> dict[str, Any]:
        return {
            "dry_run": settings.dry_run if self.dry_run is None else self.dry_run,
            "autofix_threshold": (
                settings.autofix_threshold if self.autofix_threshold is None
                else self.autofix_threshold
            ),
            "alert_threshold": (
                settings.alert_threshold if self.alert_threshold is None
                else self.alert_threshold
            ),
            "max_docs_per_change": (
                settings.max_docs_per_change if self.max_docs_per_change is None
                else self.max_docs_per_change
            ),
        }


def _finding(status: str, change: dict, doc: dict | None = None,
             verdict: dict | None = None, url: str = "",
             note: str = "") -> dict[str, Any]:
    """Normalise one outcome into the shape db.save_run and the UI expect."""
    verdict = verdict or {}
    return {
        "status": status,
        "change": {
            "file": change.get("file", ""),
            "kind": change.get("kind", ""),
            "name": change.get("name", ""),
            "detail": change.get("detail", ""),
        },
        "doc": doc or {},
        "confidence": verdict.get("confidence", 0.0),
        "mismatch": note or verdict.get("mismatch", ""),
        "suggested_fix": verdict.get("suggested_fix", ""),
        "url": url,
    }


def _doc_meta(verdict: dict) -> dict[str, Any]:
    return {
        "file": verdict.get("doc_file", ""),
        "heading": verdict.get("doc_heading", ""),
        "start_line": verdict.get("doc_start_line", 0),
        "end_line": verdict.get("doc_end_line", 0),
    }


def _act(change: dict, verdict: dict, opts: dict, commit_hash: str) -> dict[str, Any]:
    """Route one diverged verdict to a PR, an issue, or nothing."""
    doc = _doc_meta(verdict)
    confidence = verdict["confidence"]

    if confidence >= opts["autofix_threshold"] and verdict["suggested_fix"]:
        passed, reason = verify_fix(change, verdict["suggested_fix"], verdict)
        if passed:
            try:
                url = open_fix_pr(verdict, change, dry_run=opts["dry_run"])
                return _finding("auto_fixed", change, doc, verdict, url)
            except (FixError, GitHubError, GitOpsError) as e:
                # The fix could not be shipped, but the drift is real; fall
                # back to telling a human rather than dropping the finding.
                log.warning("auto-fix failed, escalating to an issue: %s", e)
                why = f"the fix was verified but could not be opened as a PR ({e})"
                url = open_docs_lie_issue(verdict, change, commit_hash=commit_hash,
                                          dry_run=opts["dry_run"], reason=why)
                return _finding("fix_failed_verification", change, doc, verdict, url,
                                note=f"auto-fix failed ({e}); {verdict['mismatch']}")
        url = open_docs_lie_issue(verdict, change, commit_hash=commit_hash,
                                  dry_run=opts["dry_run"],
                                  reason=f"the drafted fix did not pass self-verification ({reason})")
        return _finding("fix_failed_verification", change, doc, verdict, url,
                        note=f"{reason}; {verdict['mismatch']}")

    if confidence >= opts["alert_threshold"]:
        url = open_docs_lie_issue(verdict, change, commit_hash=commit_hash,
                                  dry_run=opts["dry_run"])
        return _finding("alerted", change, doc, verdict, url)

    return _finding("low_confidence_skip", change, doc, verdict)


def run_pipeline(commit_hash: str, options: RunOptions | None = None) -> list[dict[str, Any]]:
    """Analyse one commit. Returns a list of findings.

    Raises GitOpsError if the repo or commit cannot be read; individual change
    failures are captured as findings so one bad change cannot abort the run.
    """
    opts = (options or RunOptions()).resolved()
    results: list[dict[str, Any]] = []

    # PERCEIVE
    repo_path = ensure_repo(fetch=False)
    file_changes = get_commit_changes(repo_path, commit_hash)
    report = analyze_commit(file_changes)
    if report["total"] == 0:
        return [_finding("no_semantic_changes", {},
                         note="commit touched no Python signatures")]

    n_sections = retrieval.reindex(str(repo_path))   # docs may have changed too
    if n_sections == 0:
        return [_finding("no_docs_indexed", {},
                         note=f"no markdown found in {settings.target_repo or repo_path}")]
    log.info("indexed %d doc sections; %d semantic changes", n_sections, report["total"])

    for change in report["changes"]:
        # REASON
        docs = link_change_to_docs(change, n=opts["max_docs_per_change"])
        if not docs:
            results.append(_finding("no_linked_docs", change,
                                    note="no doc section mentions this code"))
            continue

        for doc in docs:
            try:
                verdict = check_divergence(change, doc)
                if not verdict["diverged"]:
                    results.append(_finding("clean", change, _doc_meta(verdict), verdict))
                    continue
                # ACT (+ VERIFY, for the auto-fix path)
                results.append(_act(change, verdict, opts, commit_hash))
            except Exception as e:  # noqa: BLE001 - one change must not kill the run
                log.exception("change %r failed", change.get("name"))
                # doc["meta"] is already in the finding's doc shape; it does
                # not need _doc_meta, which unpacks a verdict.
                results.append(_finding("error", change, doc.get("meta", {}),
                                        note=f"{type(e).__name__}: {e}"))
    return results


def main() -> int:
    import json
    import sys

    from docsentry.core.git_ops import latest_commit_hash

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    problems = settings.validate_for_run()
    if problems:
        print("Not ready to run:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    repo_path = ensure_repo()
    commit = sys.argv[1] if len(sys.argv) > 1 else latest_commit_hash(repo_path)
    print(json.dumps(run_pipeline(commit), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
