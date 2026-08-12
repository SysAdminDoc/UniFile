"""Enforce bounded complexity budgets for the desktop orchestration modules."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ComplexityBudget:
    """Hard upper bounds that prevent the orchestration seam growing silently."""

    max_lines: int
    max_methods: int
    max_method_lines: int


MODULE_BUDGETS = {
    "unifile/main_window.py": ComplexityBudget(5_000, 190, 1_400),
    "unifile/workers.py": ComplexityBudget(3_600, 95, 950),
    "unifile/window_controllers.py": ComplexityBudget(360, 30, 180),
}


def _module_stats(path: Path) -> tuple[int, int, int, str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    methods = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    largest = max(methods, key=lambda node: node.end_lineno - node.lineno + 1, default=None)
    largest_lines = 0 if largest is None else largest.end_lineno - largest.lineno + 1
    largest_name = "" if largest is None else largest.name
    return len(source.splitlines()), len(methods), largest_lines, largest_name


def check_complexity(root: Path = ROOT) -> list[str]:
    """Return file-specific budget failures for the orchestration modules."""
    errors: list[str] = []
    for relative, budget in MODULE_BUDGETS.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"{relative}: module is missing")
            continue
        lines, methods, largest_lines, largest_name = _module_stats(path)
        if lines > budget.max_lines:
            errors.append(f"{relative}: {lines} lines exceeds budget {budget.max_lines}")
        if methods > budget.max_methods:
            errors.append(f"{relative}: {methods} methods exceeds budget {budget.max_methods}")
        if largest_lines > budget.max_method_lines:
            errors.append(
                f"{relative}: method {largest_name!r} is {largest_lines} lines; "
                f"budget is {budget.max_method_lines}"
            )
    return errors


def main() -> int:
    errors = check_complexity()
    if errors:
        for error in errors:
            print(f"complexity contract failed: {error}")
        return 1
    print("complexity contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
