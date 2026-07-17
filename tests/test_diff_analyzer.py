"""Semantic change detection via tree-sitter."""
from __future__ import annotations

from docsentry.agents.diff_analyzer import (
    analyze_commit,
    analyze_file_change,
    extract_functions,
)
from docsentry.core.git_ops import FileChange, get_commit_changes, latest_commit_hash


def _change(before: str, after: str, path: str = "calculator.py"):
    return analyze_file_change(FileChange(path=path, change_type="modified",
                                          before=before, after=after))


def test_flipped_default_is_its_own_kind():
    """The flagship case. v1 declared a `default_changed` kind but never
    emitted it, reporting a generic params_changed instead."""
    changes = _change("def divide(a, b, safe=True):\n    pass\n",
                      "def divide(a, b, safe=False):\n    pass\n")
    assert [c.kind for c in changes] == ["default_changed"]
    assert "safe" in changes[0].detail
    assert "True" in changes[0].detail and "False" in changes[0].detail


def test_added_and_removed_params_are_params_changed():
    changes = _change("def f(a, b):\n    pass\n", "def f(a, b, c):\n    pass\n")
    assert [c.kind for c in changes] == ["params_changed"]


def test_cosmetic_edits_produce_nothing():
    """Whitespace and comments must not raise a finding, or the agent cries
    wolf on every reformat."""
    before = "def f(a, b):\n    return a+b\n"
    after = "def f(a, b):\n    # a comment\n    return a + b\n"
    assert _change(before, after) == []


def test_function_added_and_removed():
    added = _change("", "def brand_new(x):\n    pass\n")
    assert [c.kind for c in added] == ["function_added"]

    removed = _change("def gone(x):\n    pass\n", "")
    assert [c.kind for c in removed] == ["function_removed"]


def test_same_name_in_two_classes_does_not_collide():
    """v1 keyed on the bare name, so Legacy.divide overwrote Calc.divide and
    a change to one was invisible."""
    src = (
        "class Calc:\n"
        "    def divide(self, a, b, safe=True):\n        pass\n"
        "class Legacy:\n"
        "    def divide(self, a, b, safe=True):\n        pass\n"
    )
    funcs = extract_functions(src)
    assert "Calc.divide" in funcs
    assert "Legacy.divide" in funcs

    after = src.replace(
        "class Legacy:\n    def divide(self, a, b, safe=True):",
        "class Legacy:\n    def divide(self, a, b, safe=False):",
    )
    changes = _change(src, after)
    assert len(changes) == 1
    assert changes[0].name == "Legacy.divide"


def test_return_type_change_detected():
    changes = _change("def f(a) -> int:\n    pass\n", "def f(a) -> str:\n    pass\n")
    assert [c.kind for c in changes] == ["return_type_changed"]


def test_annotation_change_detected():
    changes = _change("def f(a: int):\n    pass\n", "def f(a: str):\n    pass\n")
    assert [c.kind for c in changes] == ["params_changed"]
    assert "int" in changes[0].detail and "str" in changes[0].detail


def test_docstring_change_detected():
    changes = _change('def f(a):\n    """Old."""\n', 'def f(a):\n    """New."""\n')
    assert [c.kind for c in changes] == ["docstring_changed"]


def test_non_python_files_ignored():
    assert _change("# Title", "# Other", path="README.md") == []


def test_star_args_parsed():
    funcs = extract_functions("def f(a, *args, key=1, **kwargs):\n    pass\n")
    assert funcs["f"].param_names() == ["a", "*args", "key", "**kwargs"]


def test_syntax_error_does_not_crash():
    """tree-sitter is error-tolerant; a broken push must not kill the run."""
    assert isinstance(_change("def f(:\n", "def g(:\n"), list)


def test_analyze_commit_over_real_repo(repo):
    """End to end against the fixture repo's actual flipped-default commit."""
    fcs = get_commit_changes(repo, latest_commit_hash(repo))
    report = analyze_commit(fcs)
    assert report["total"] >= 1
    kinds = [c["kind"] for c in report["changes"]]
    assert "default_changed" in kinds
