"""The PERCEIVE step: raw file changes -> semantic ChangeReport, via tree-sitter.

Comparing ASTs rather than text means reformatting, comment edits and moved
code produce no findings, while a flipped default deep inside a signature
produces a precise one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from docsentry.core.git_ops import FileChange

PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)


@dataclass
class Param:
    name: str
    annotation: str = ""
    default: str = ""

    def render(self) -> str:
        out = self.name
        if self.annotation:
            out += f": {self.annotation}"
        if self.default:
            out += f"={self.default}"
        return out


@dataclass
class FunctionSig:
    name: str                       # qualified, e.g. "Calculator.divide"
    params: list[Param] = field(default_factory=list)
    returns: str = ""
    docstring: str = ""

    def render(self) -> str:
        return f"{self.name}({', '.join(p.render() for p in self.params)})"

    def param_names(self) -> list[str]:
        return [p.name for p in self.params]

    def defaults(self) -> dict[str, str]:
        return {p.name: p.default for p in self.params if p.default}


@dataclass
class SemanticChange:
    file: str
    kind: str    # function_added | function_removed | params_changed |
                 # default_changed | return_type_changed | docstring_changed
    name: str
    detail: str


def _text(node: Node | None, src: bytes) -> str:
    if node is None:
        return ""
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _parse_param(node: Node, src: bytes) -> Param | None:
    t = node.type
    if t == "identifier":
        return Param(name=_text(node, src))
    if t == "default_parameter":
        return Param(name=_text(node.child_by_field_name("name"), src),
                     default=_text(node.child_by_field_name("value"), src))
    if t == "typed_parameter":
        # typed_parameter exposes no "name" field; the identifier is a child.
        ident = next((c for c in node.children if c.type == "identifier"), None)
        return Param(name=_text(ident, src),
                     annotation=_text(node.child_by_field_name("type"), src))
    if t == "typed_default_parameter":
        return Param(name=_text(node.child_by_field_name("name"), src),
                     annotation=_text(node.child_by_field_name("type"), src),
                     default=_text(node.child_by_field_name("value"), src))
    if t == "list_splat_pattern":
        return Param(name=f"*{_text(node, src).lstrip('*')}")
    if t == "dictionary_splat_pattern":
        return Param(name=f"**{_text(node, src).lstrip('*')}")
    if t in ("keyword_separator", "positional_separator"):
        return Param(name=_text(node, src))
    return None


def _docstring_of(body: Node | None, src: bytes) -> str:
    if not body or body.named_child_count == 0:
        return ""
    first = body.named_children[0]
    if first.type == "expression_statement" and first.named_children:
        inner = first.named_children[0]
        if inner.type == "string":
            return _text(inner, src).strip("\"' \n")
    return ""


def extract_functions(source: str) -> dict[str, FunctionSig]:
    """Parse Python source into {qualified_name: FunctionSig}.

    Names are qualified by their enclosing class or function, so
    Calculator.divide and Legacy.divide are distinct. v1 keyed on the bare
    name, so same-named methods in different classes overwrote one another and
    any difference between them was invisible.
    """
    src = source.encode("utf-8")
    tree = _parser.parse(src)
    out: dict[str, FunctionSig] = {}

    def walk(node: Node, scope: list[str]) -> None:
        inner_scope = scope
        if node.type == "function_definition":
            name = _text(node.child_by_field_name("name"), src)
            qualified = ".".join([*scope, name])
            params_node = node.child_by_field_name("parameters")
            params: list[Param] = []
            if params_node:
                for child in params_node.named_children:
                    p = _parse_param(child, src)
                    if p:
                        params.append(p)
            out[qualified] = FunctionSig(
                name=qualified,
                params=params,
                returns=_text(node.child_by_field_name("return_type"), src),
                docstring=_docstring_of(node.child_by_field_name("body"), src),
            )
            inner_scope = [*scope, name]
        elif node.type == "class_definition":
            inner_scope = [*scope, _text(node.child_by_field_name("name"), src)]

        for child in node.children:
            walk(child, inner_scope)

    walk(tree.root_node, [])
    return out


def _compare(before: FunctionSig, after: FunctionSig, path: str) -> list[SemanticChange]:
    changes: list[SemanticChange] = []
    name = after.name

    if before.param_names() != after.param_names():
        changes.append(SemanticChange(
            path, "params_changed", name,
            f"`{name}` signature changed: "
            f"({', '.join(p.render() for p in before.params)}) → "
            f"({', '.join(p.render() for p in after.params)})"))
    else:
        # Same parameter list, so any difference is in the defaults or types.
        # A flipped default is the highest-signal case for doc drift: the docs
        # state the old value in prose and nothing else looks different.
        b_def, a_def = before.defaults(), after.defaults()
        for pname in sorted(set(b_def) | set(a_def)):
            old, new = b_def.get(pname), a_def.get(pname)
            if old == new:
                continue
            if old is None:
                detail = f"`{name}` parameter `{pname}` gained a default of `{new}`"
            elif new is None:
                detail = f"`{name}` parameter `{pname}` lost its default (was `{old}`)"
            else:
                detail = f"`{name}` default for `{pname}` changed: `{old}` → `{new}`"
            changes.append(SemanticChange(path, "default_changed", name, detail))

        b_ann = {p.name: p.annotation for p in before.params}
        for p in after.params:
            old_ann = b_ann.get(p.name, "")
            if old_ann != p.annotation:
                changes.append(SemanticChange(
                    path, "params_changed", name,
                    f"`{name}` type of `{p.name}` changed: "
                    f"`{old_ann or 'untyped'}` → `{p.annotation or 'untyped'}`"))

    if before.returns != after.returns:
        changes.append(SemanticChange(
            path, "return_type_changed", name,
            f"`{name}` return type changed: `{before.returns or 'unannotated'}` → "
            f"`{after.returns or 'unannotated'}`"))

    if before.docstring != after.docstring:
        changes.append(SemanticChange(
            path, "docstring_changed", name, f"`{name}` docstring changed"))

    return changes


def analyze_file_change(fc: FileChange) -> list[SemanticChange]:
    """Compare before/after function signatures for one file."""
    if not fc.path.endswith(".py"):
        return []

    before = extract_functions(fc.before) if fc.before else {}
    after = extract_functions(fc.after) if fc.after else {}
    changes: list[SemanticChange] = []

    for name in sorted(after.keys() - before.keys()):
        changes.append(SemanticChange(
            fc.path, "function_added", name, f"New function `{after[name].render()}`"))
    for name in sorted(before.keys() - after.keys()):
        changes.append(SemanticChange(
            fc.path, "function_removed", name, f"Function `{name}` was deleted"))
    for name in sorted(before.keys() & after.keys()):
        changes.extend(_compare(before[name], after[name], fc.path))
    return changes


def analyze_commit(file_changes: list[FileChange]) -> dict[str, Any]:
    """Full ChangeReport for a commit."""
    all_changes: list[SemanticChange] = []
    for fc in file_changes:
        all_changes.extend(analyze_file_change(fc))
    return {"total": len(all_changes), "changes": [asdict(c) for c in all_changes]}
