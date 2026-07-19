"""Markdown sectioning."""
from __future__ import annotations

from docsentry.core.parser import collect_doc_sections, parse_markdown


def _sections(tmp_path, text, name="doc.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return parse_markdown(p, tmp_path)


def test_splits_on_headings(tmp_path):
    secs = _sections(tmp_path, "# One\n\nalpha\n\n## Two\n\nbeta\n")
    assert [s.heading for s in secs] == ["One", "Two"]
    assert "alpha" in secs[0].content
    assert "beta" in secs[1].content


def test_hash_inside_code_fence_is_not_a_heading(tmp_path):
    """The bug this guards: docs are mostly code samples, and a `# comment`
    inside a ```python block used to split the section in half."""
    text = (
        "# Usage\n"
        "\n"
        "```python\n"
        "# this is a comment, not a heading\n"
        "divide(1, 0)\n"
        "```\n"
        "\n"
        "Trailing prose.\n"
    )
    secs = _sections(tmp_path, text)
    assert [s.heading for s in secs] == ["Usage"]
    assert "# this is a comment, not a heading" in secs[0].content
    assert "Trailing prose." in secs[0].content


def test_tilde_fence_also_respected(tmp_path):
    secs = _sections(tmp_path, "# T\n\n~~~\n# not a heading\n~~~\n")
    assert [s.heading for s in secs] == ["T"]


def test_end_line_excludes_trailing_blanks(tmp_path):
    """end_line drives the auto-fix splice; an over-wide range eats the blank
    line separating two sections."""
    text = "# One\n\nalpha\n\n\n# Two\n\nbeta\n"
    secs = _sections(tmp_path, text)
    lines = text.splitlines()
    first = secs[0]
    # The recorded range must contain exactly the section's own text.
    assert lines[first.start_line - 1] == "# One"
    assert lines[first.end_line - 1].strip() == "alpha"


def test_section_range_round_trips(tmp_path):
    """Slicing the file by (start_line, end_line) must reproduce the content."""
    text = "# One\n\nalpha\nbeta\n\n## Two\n\ngamma\n"
    secs = _sections(tmp_path, text)
    lines = text.splitlines()
    for s in secs:
        sliced = "\n".join(lines[s.start_line - 1:s.end_line]).strip()
        assert sliced == s.content


def test_intro_before_first_heading(tmp_path):
    secs = _sections(tmp_path, "preamble text\n\n# One\n\nalpha\n")
    assert secs[0].heading == "(intro)"
    assert "preamble" in secs[0].content


def test_closing_hashes_stripped(tmp_path):
    secs = _sections(tmp_path, "## Title ##\n\nbody\n")
    assert secs[0].heading == "Title"


def test_collect_skips_vendored_dirs(tmp_path):
    (tmp_path / "README.md").write_text("# Real\n\nkeep\n", encoding="utf-8")
    vendored = tmp_path / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "README.md").write_text("# Vendored\n\ndrop\n", encoding="utf-8")

    headings = {s.heading for s in collect_doc_sections(str(tmp_path))}
    assert "Real" in headings
    assert "Vendored" not in headings


def test_collect_on_missing_dir_is_empty():
    assert collect_doc_sections("/definitely/not/a/path") == []


def test_ids_are_stable_and_unique(tmp_path):
    secs = _sections(tmp_path, "# A\n\nx\n\n# B\n\ny\n")
    ids = [s.id for s in secs]
    assert len(set(ids)) == len(ids)
    assert all("doc.md" in i for i in ids)
