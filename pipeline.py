"""PERCEIVE → REASON → ACT → VERIFY, end to end for one commit."""
from docsentry.config import settings
from docsentry.core.git_ops import get_commit_changes
from docsentry.core.vector_store import reindex
from docsentry.agents.diff_analyzer import analyze_commit
from docsentry.agents.doc_linker import link_change_to_docs
from docsentry.agents.divergence import check_divergence
from docsentry.agents.auto_fixer import open_fix_pr, apply_fix_locally
from docsentry.agents.alerter import open_docs_lie_issue
from docsentry.agents.verifier import verify_fix


def run_pipeline(commit_hash: str) -> list[dict]:
    results = []

    # PERCEIVE
    file_changes = get_commit_changes(settings.local_repo_path, commit_hash)
    report = analyze_commit(file_changes)
    if report["total"] == 0:
        return [{"status": "no_semantic_changes"}]

    reindex(settings.local_repo_path)   # docs may have changed too

    for change in report["changes"]:
        # REASON — link, then judge the single best-matching section
        docs = link_change_to_docs(change, n=3)
        for doc in docs:
            verdict = check_divergence(change, doc)
            verdict["doc_start_line"] = doc["meta"]["start_line"]
            verdict["doc_end_line"] = doc["meta"]["end_line"]

            if not verdict["diverged"]:
                results.append({"status": "clean", "change": change["detail"],
                                "doc": verdict["doc_file"]})
                continue

            # ACT
            if verdict["confidence"] >= settings.autofix_threshold and verdict["suggested_fix"]:
                fixed_content = verdict["suggested_fix"]
                if verify_fix(change, fixed_content, verdict):        # VERIFY
                    url = open_fix_pr(verdict, change)
                    results.append({"status": "auto_fixed", "pr": url,
                                    "change": change["detail"]})
                else:
                    url = open_docs_lie_issue(verdict, change)
                    results.append({"status": "fix_failed_verification",
                                    "issue": url})
            elif verdict["confidence"] >= settings.alert_threshold:
                url = open_docs_lie_issue(verdict, change)
                results.append({"status": "alerted", "issue": url,
                                "change": change["detail"]})
            else:
                results.append({"status": "low_confidence_skip",
                                "change": change["detail"]})
    return results


if __name__ == "__main__":
    import sys, json
    from docsentry.core.git_ops import latest_commit_hash
    commit = sys.argv[1] if len(sys.argv) > 1 else latest_commit_hash(settings.local_repo_path)
    print(json.dumps(run_pipeline(commit), indent=2))
