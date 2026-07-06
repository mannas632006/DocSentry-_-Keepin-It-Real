"""Apply the suggested fix to the doc, push a branch, open a PR."""
import time
from pathlib import Path

from git import Repo
from github import Github

from docsentry.config import settings


def apply_fix_locally(verdict: dict) -> str | None:
    """Replace the diverged section content in the doc file. Returns new content or None."""
    doc_path = Path(settings.local_repo_path) / verdict["doc_file"]
    text = doc_path.read_text(encoding="utf-8")

    lines = text.splitlines()
    start = verdict["doc_start_line"] - 1
    end = verdict["doc_end_line"]
    fixed_section = verdict["suggested_fix"].splitlines()
    new_lines = lines[:start] + fixed_section + lines[end:]
    new_text = "\n".join(new_lines) + "\n"
    doc_path.write_text(new_text, encoding="utf-8")
    return new_text


def open_fix_pr(verdict: dict, change: dict) -> str:
    """Branch, commit, push, and open a PR. Returns the PR URL."""
    repo = Repo(settings.local_repo_path)
    base_branch = repo.active_branch.name
    branch = f"docsentry/fix-{int(time.time())}"
    repo.git.checkout("-b", branch)

    apply_fix_locally(verdict)

    repo.git.add(verdict["doc_file"])
    repo.index.commit(f"docs: fix drift in {verdict['doc_file']} ({verdict['doc_heading']})")
    repo.git.push("--set-upstream", "origin", branch)
    repo.git.checkout(base_branch)   # leave working tree clean

    gh = Github(settings.github_token)
    gh_repo = gh.get_repo(settings.target_repo)
    pr = gh_repo.create_pull(
        title=f"🤖 DocSentry: fix documentation drift in {verdict['doc_file']}",
        body=f"""## Documentation drift detected

**Triggering change:** `{change['detail']}` in `{change['file']}`

**The lie:** {verdict['mismatch']}

**Confidence:** {verdict['confidence']:.0%}

This PR was opened automatically. Review before merging.""",
        head=branch,
        base=base_branch,
    )
    return pr.html_url
