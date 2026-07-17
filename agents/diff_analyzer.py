"""Turn raw file changes into a semantic ChangeReport using tree-sitter."""
from dataclasses import dataclass, field, asdict

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from docsentry.core.git_ops import FileChange

PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)


@dataclass
class FunctionSig:
    name: str
    params: list[str]              # e.g. ["a", "b", "safe=True"]
    docstring: str = ""

    def key(self) -> str:
        return self.name


@dataclass
class SemanticChange:
    file: str
    kind: str        # function_added | function_removed | params_changed |
                     # default_changed | docstring_changed
    name: str
    detail: str


def _node_text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def extract_functions(source: str) -> dict[str, FunctionSig]:
    """Parse Python source, return {func_name: FunctionSig}."""
    src = source.encode("utf-8")
    tree = _parser.parse(src)
    out: dict[str, FunctionSig] = {}

    def walk(node):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            name = _node_text(name_node, src)

            params = []
            for child in params_node.named_children:
                params.append(_node_text(child, src))

            # first statement in body that's a string = docstring
            body = node.child_by_field_name("body")
            doc = ""
            if body and body.named_child_count > 0:
                first = body.named_children[0]
                if first.type == "expression_statement" and \
                   first.named_children and first.named_children[0].type == "string":
                    doc = _node_text(first.named_children[0], src).strip("\"' \n")
            out[name] = FunctionSig(name=name, params=params, docstring=doc)
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return out


def analyze_file_change(fc: FileChange) -> list[SemanticChange]:
    """Compare before/after function signatures for one file."""
    if not fc.path.endswith(".py"):
        return []

    before = extract_functions(fc.before) if fc.before else {}
    after = extract_functions(fc.after) if fc.after else {}
    changes: list[SemanticChange] = []

    for name in after.keys() - before.keys():
        changes.append(SemanticChange(fc.path, "function_added", name,
                                      f"New function `{name}({', '.join(after[name].params)})`"))
    for name in before.keys() - after.keys():
        changes.append(SemanticChange(fc.path, "function_removed", name,
                                      f"Function `{name}` was deleted"))
    for name in before.keys() & after.keys():
        b, a = before[name], after[name]
        if b.params != a.params:
            changes.append(SemanticChange(
                fc.path, "params_changed", name,
                f"`{name}` signature changed: ({', '.join(b.params)}) → ({', '.join(a.params)})"))
        if b.docstring != a.docstring:
            changes.append(SemanticChange(
                fc.path, "docstring_changed", name,
                f"`{name}` docstring changed"))
    return changes


def analyze_commit(file_changes: list[FileChange]) -> dict:
    """Full ChangeReport for a commit."""
    all_changes: list[SemanticChange] = []
    for fc in file_changes:
        all_changes.extend(analyze_file_change(fc))
    return {
        "total": len(all_changes),
        "changes": [asdict(c) for c in all_changes],
    }