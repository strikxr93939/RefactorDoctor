import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def interface_fingerprint(code: str) -> dict[str, tuple[int, int, bool, bool]]:
    tree = ast.parse(code)
    result: dict[str, tuple[int, int, bool, bool]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result[node.name] = (
                len(node.args.posonlyargs) + len(node.args.args),
                len(node.args.kwonlyargs),
                node.args.vararg is not None,
                node.args.kwarg is not None,
            )
    return result


def validate_candidate(original: str, candidate: str) -> tuple[bool, bool]:
    ast.parse(candidate)
    compile(candidate, "<refactored>", "exec")
    return True, interface_fingerprint(original) == interface_fingerprint(candidate)


def pylint_score(code: str) -> float | None:
    with tempfile.TemporaryDirectory(prefix="refactor-pylint-") as raw:
        path = Path(raw) / "candidate.py"
        path.write_text(code, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pylint", "--score=y", "--reports=n", str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
    match = re.search(r"rated at\s+(-?\d+(?:\.\d+)?)/10", result.stdout + result.stderr)
    return float(match.group(1)) if match else None
