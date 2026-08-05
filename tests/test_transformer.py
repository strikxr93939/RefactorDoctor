import ast

from refactor_doctor.transformer import transform_legacy_code
from refactor_doctor.validation import interface_fingerprint, validate_candidate

LEGACY = """import os

def total(values):
    result = sum(values)
    print('total', result)
    return result

def location(root, name):
    return os.path.join(root, name)
"""


def test_modernizes_print_path_types_and_docs() -> None:
    result, changes = transform_legacy_code(LEGACY)

    ast.parse(result)
    assert "logger.info" in result
    assert "Path(root).joinpath(name)" in result
    assert "values: Any" in result
    assert '"""Total.' in result
    assert len(changes) >= 4


def test_preserves_signatures_and_simple_behavior() -> None:
    result, _ = transform_legacy_code(LEGACY)
    syntax_valid, interface_valid = validate_candidate(LEGACY, result)
    original_ns: dict[str, object] = {}
    refactored_ns: dict[str, object] = {}
    exec(LEGACY, original_ns)  # noqa: S102 - controlled test fixture
    exec(result, refactored_ns)  # noqa: S102 - controlled test fixture

    assert syntax_valid and interface_valid
    assert interface_fingerprint(LEGACY) == interface_fingerprint(result)
    assert original_ns["total"]([1, 2, 3]) == refactored_ns["total"]([1, 2, 3])
    assert original_ns["location"]("a", "b") == refactored_ns["location"]("a", "b")
