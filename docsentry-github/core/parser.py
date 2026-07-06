"""Parse markdown files into heading-anchored sections."""
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DocSection:
    file: str
    heading: str
    content: str
    start_line: int
    end_line: int

    @property
    def id(self) -> str:
        return f"{self.file}::{self.start_line}"


def parse_markdown(path: Path, rel_to: Path) -> list[DocSection]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    sections: list[DocSection] = []
    cur_heading, cur_start, buf = "(intro)", 1, []

    def flush(end_line: int):
        if buf and "".join(buf).strip():
            sections.append(DocSection(
                file=str(path.relative_to(rel_to)),
                heading=cur_heading,
                content="\n".join(buf).strip(),
                start_line=cur_start,
                end_line=end_line,
            ))

    for i, line in enumerate(lines, start=1):
        if re.match(r"^#{1,6}\s", line):
            flush(i - 1)
            cur_heading = line.lstrip("#").strip()
            cur_start = i
            buf = [line]
        else:
            buf.append(line)
    flush(len(lines))
    return sections


def collect_doc_sections(repo_path: str) -> list[DocSection]:
    root = Path(repo_path)
    sections = []
    for md in root.rglob("*.md"):
        if ".git" in md.parts:
            continue
        sections.extend(parse_markdown(md, root))
    return sections