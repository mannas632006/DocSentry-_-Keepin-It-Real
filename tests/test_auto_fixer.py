"""Applying a suggested fix to a doc file."""
from __future__ import annotations

import pytest

from docsentry.agents.auto_fixer import FixError, apply_fix_locally, render_fixed_doc

DOC = """# Calculator

## divide

By default `safe` is **True**, so dividing by zero returns `None`.

## Notes

Nothing else to say.
"""


@pytest.fixture
def docfile(tmp_path):
    (tmp_path / "README.md").write_text(DOC, encoding="utf-8")
    return tmp_path


def _verdict(fix, start=3, end=5):
    return {
        "doc_file": "README.md",
        "doc_heading": "divide",
        "doc_start_line": start,
        "doc_end_line": end,
        "suggested_fix": fix,
    }


def test_replaces_only_the_target_section(docfile):
    fix = "## divide\n\nBy default `safe` is **False**, so dividing by zero raises."
    out = render_fixed_doc(docfile, _verdict(fix))

    assert "**False**" in out
    assert "**True**" not in out
    # Everything outside the section must survive untouched.
    assert "# Calculator" in out
    assert "## Notes" in out
    assert "Nothing else to say." in out


def test_full_section_fix_preserves_neighbouring_sections(docfile):
    """The v1 prompt asked for 'ONLY the false lines' while the splice replaced
    the section's whole line range — so a one-line fix silently deleted the
    rest of the section. The prompt now demands the complete section; this
    pins the splice to that contract."""
    out = render_fixed_doc(docfile, _verdict("## divide\n\nAll new text."))
    lines = out.splitlines()
    assert "# Calculator" in lines
    assert "## divide" in lines
    assert "All new text." in lines
    assert "## Notes" in lines
    # The blank line separating divide from Notes must still be there.
    assert lines[lines.index("All new text.") + 1] == ""


def test_writes_to_disk(docfile):
    apply_fix_locally(docfile, _verdict("## divide\n\nPatched."))
    assert "Patched." in (docfile / "README.md").read_text(encoding="utf-8")


def test_empty_fix_rejected(docfile):
    with pytest.raises(FixError, match="no suggested_fix"):
        render_fixed_doc(docfile, _verdict("   "))


def test_identical_fix_rejected(docfile):
    """A no-op fix would open an empty PR."""
    section = "## divide\n\nBy default `safe` is **True**, so dividing by zero returns `None`."
    with pytest.raises(FixError, match="identical"):
        render_fixed_doc(docfile, _verdict(section))


def test_missing_doc_file_rejected(docfile):
    v = _verdict("## divide\n\nx")
    v["doc_file"] = "NOPE.md"
    with pytest.raises(FixError, match="not found"):
        render_fixed_doc(docfile, v)


def test_out_of_range_section_rejected(docfile):
    """Line numbers come from an index built before the fix was drafted. If the
    file changed underneath, splicing by stale offsets would corrupt it."""
    with pytest.raises(FixError, match="outside"):
        render_fixed_doc(docfile, _verdict("## divide\n\nx", start=1, end=9999))


def test_inverted_range_rejected(docfile):
    with pytest.raises(FixError, match="outside"):
        render_fixed_doc(docfile, _verdict("## divide\n\nx", start=8, end=3))


def test_output_ends_with_single_newline(docfile):
    out = render_fixed_doc(docfile, _verdict("## divide\n\nPatched."))
    assert out.endswith("\n")
    assert not out.endswith("\n\n")
