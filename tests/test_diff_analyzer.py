from docsentry.core.git_ops import get_commit_changes, latest_commit_hash
from docsentry.agents.diff_analyzer import analyze_commit
from docsentry.config import settings


def test_detects_default_change():
    commit = latest_commit_hash(settings.local_repo_path)
    fcs = get_commit_changes(settings.local_repo_path, commit)
    report = analyze_commit(fcs)
    print(report)
    kinds = [c["kind"] for c in report["changes"]]
    assert "params_changed" in kinds