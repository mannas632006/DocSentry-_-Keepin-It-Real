"""Parse markdown files into heading-anchored sections."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DOC_SUFFIXES = {".md", ".markdown", ".mdx"}

# Directories that never contain hand-written docs but often contain a great
# deal of markdown (vendored READMEs, generated changelogs).
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "dist", "build", "site-packages", ".next", ".docsentry",
}

_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*)")
# ``` or ~~~, optionally indented, optionally with an info string.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


@dataclass
class DocSection:
    file: str
    heading: str
    content: str
    start_line: int      # 1-based, inclusive; the heading line itself
    end_line: int        # 1-based, inclusive; last non-blank line

    @property
    def id(self) -> str:
        return f"{self.file}::{self.start_line}"


def parse_markdown(path: Path, rel_to: Path) -> list[DocSection]:
    """Split one markdown file into sections, one per heading.

    Fenced code blocks are tracked so that a `# comment` inside a ```python
    block is not mistaken for a markdown heading — which matters a lot here,
    since the docs this agent reads are mostly code samples.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    try:
        rel = str(path.relative_to(rel_to))
    except ValueError:
        rel = str(path)
    rel = rel.replace("\\", "/")

    sections: list[DocSection] = []
    cur_heading = "(intro)"
    cur_start = 1
    buf: list[str] = []
    fence: str | None = None      # the opening fence marker, when inside one

    def flush(end_line: int) -> None:
        content = "\n".join(buf).strip()
        if not content:
            return
        # Walk back over trailing blank lines so the recorded range covers
        # exactly the text in `content`. auto_fixer splices by this range, and
        # over-wide ranges swallow the blank line between sections.
        last = end_line
        while last > cur_start and last - 1 < len(lines) and not lines[last - 1].strip():
            last -= 1
        sections.append(DocSection(
            file=rel,
            heading=cur_heading,
            content=content,
            start_line=cur_start,
            end_line=last,
        ))

    for i, line in enumerate(lines, start=1):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                # An opening fence must not have a marker in its info string.
                if "`" not in fence_match.group(2):
                    fence = marker[0] * 3
            elif marker[0] == fence[0] and len(marker) >= 3:
                fence = None
            buf.append(line)
            continue

        heading_match = _HEADING_RE.match(line) if fence is None else None
        if heading_match:
            flush(i - 1)
            cur_heading = heading_match.group(2).strip().rstrip("#").strip()
            cur_start = i
            buf = [line]
        else:
            buf.append(line)

    flush(len(lines))
    return sections


def collect_doc_sections(repo_path: str) -> list[DocSection]:
    """Every doc section in every markdown file under repo_path."""
    root = Path(repo_path)
    if not root.is_dir():
        return []
    sections: list[DocSection] = []
    for doc in sorted(root.rglob("*")):
        if doc.suffix.lower() not in DOC_SUFFIXES or not doc.is_file():
            continue
        if any(part in SKIP_DIRS for part in doc.relative_to(root).parts):
            continue
        sections.extend(parse_markdown(doc, root))
    return sections
