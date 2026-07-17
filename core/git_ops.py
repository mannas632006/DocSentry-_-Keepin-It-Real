"""Extract before/after file snapshots for a commit."""
from dataclasses import dataclass, field

from git import Repo


@dataclass
class FileChange:
    path: str
    change_type: str          # "added" | "modified" | "deleted"
    before: str = ""          # file content BEFORE the commit
    after: str = ""           # file content AFTER the commit


def get_commit_changes(repo_path: str, commit_hash: str) -> list[FileChange]:
    """Return FileChange objects for every file touched by the commit."""
    repo = Repo(repo_path)
    commit = repo.commit(commit_hash)
    parent = commit.parents[0] if commit.parents else None

    changes: list[FileChange] = []
    diffs = parent.diff(commit) if parent else commit.diff(None)

    for d in diffs:
        if d.new_file:
            ctype, path = "added", d.b_path
        elif d.deleted_file:
            ctype, path = "deleted", d.a_path
        else:
            ctype, path = "modified", d.b_path

        before = ""
        after = ""
        if d.a_blob and ctype != "added":
            before = d.a_blob.data_stream.read().decode("utf-8", errors="replace")
        if d.b_blob and ctype != "deleted":
            after = d.b_blob.data_stream.read().decode("utf-8", errors="replace")

        changes.append(FileChange(path=path, change_type=ctype,
                                  before=before, after=after))
    return changes


def latest_commit_hash(repo_path: str) -> str:
    return Repo(repo_path).head.commit.hexsha