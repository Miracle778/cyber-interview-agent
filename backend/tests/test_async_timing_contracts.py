from __future__ import annotations

import ast
from pathlib import Path


def _literal_timeout(call: ast.Call) -> int | float | None:
    timeout: ast.expr | None = call.args[1] if len(call.args) > 1 else None
    for keyword in call.keywords:
        if keyword.arg == "timeout":
            timeout = keyword.value
            break
    if isinstance(timeout, ast.Constant) and isinstance(timeout.value, int | float):
        return timeout.value
    return None


def test_asyncio_wait_for_uses_named_guards_instead_of_machine_speed_literals() -> None:
    tests_root = Path(__file__).parent
    violations: list[str] = []

    for path in sorted(tests_root.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not (
                isinstance(function, ast.Attribute)
                and function.attr == "wait_for"
                and isinstance(function.value, ast.Name)
                and function.value.id == "asyncio"
            ):
                continue
            timeout = _literal_timeout(node)
            if timeout is not None:
                violations.append(f"{path.name}:{node.lineno} timeout={timeout}")

    formatted_violations = "\n".join(violations)
    assert not violations, (
        "Use tests.async_test_utils or a documented named timeout constant. "
        "A numeric asyncio.wait_for timeout turns runner speed into a hidden "
        f"correctness requirement:\n{formatted_violations}"
    )
