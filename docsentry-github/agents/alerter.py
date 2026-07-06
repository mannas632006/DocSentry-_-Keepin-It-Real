"""Open a 'Docs Lie' issue for human review."""
from github import Github

from docsentry.config import settings


def open_docs_lie_issue(verdict: dict, change: dict) -> str:
    gh = Github(settings.github_token)
    repo = gh.get_repo(settings.target_repo)
    issue = repo.create_issue(
        title=f"📄🔥 Docs Lie: {verdict['doc_file']} — {verdict['doc_heading']}",
        body=f"""## Possible documentation drift

**Code change:** `{change['detail']}` in `{change['file']}`
**Doc section:** `{verdict['doc_file']}` → *{verdict['doc_heading']}*
**Suspected lie:** {verdict['mismatch']}
**Confidence:** {verdict['confidence']:.0%}

**Suggested fix:**
```
{verdict['suggested_fix'] or '(none proposed)'}
```
_Opened automatically by DocSentry._""",
    )
    return issue.html_url
