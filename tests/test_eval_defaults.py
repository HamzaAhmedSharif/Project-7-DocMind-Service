"""M4.5: the evaluation must exercise what ships, not private constants.

The AST guard fails if run_retrieval.py reintroduces hard-coded `top_k=NN`
or `chunk_pages(..., words=NN, overlap=NN)` literals instead of sourcing the
top-k from `Settings().default_top_k` and the chunk parameters from the
`chunk_pages` defaults.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _run_retrieval_tree() -> ast.Module:
    src = Path(__file__).resolve().parents[1] / "evaluation" / "run_retrieval.py"
    return ast.parse(src.read_text(encoding="utf-8"))


def _keywords(tree: ast.Module) -> list[ast.keyword]:
    return [k for node in ast.walk(tree) if isinstance(node, ast.Call) for k in node.keywords]


@pytest.mark.parametrize("name", ["top_k", "words", "overlap"])
def test_no_numeric_literal_for_shipped_parameter(name: str) -> None:
    bad = [
        k.arg
        for k in _keywords(_run_retrieval_tree())
        if k.arg == name and isinstance(k.value, ast.Constant)
    ]
    assert not bad, f"run_retrieval.py hard-codes {name}={bad}; use the shipped defaults"


def test_imports_top_k_from_settings() -> None:
    tree = _run_retrieval_tree()
    src_ast_names = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "get_settings" in src_ast_names
