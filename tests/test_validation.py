import pytest
from refactor_doctor.validation import validate_candidate


def test_rejects_changed_signature() -> None:
    original = "def calculate(value):\n    return value * 2\n"
    changed = "def calculate(value, multiplier):\n    return value * multiplier\n"

    syntax_valid, interfaces_preserved = validate_candidate(original, changed)

    assert syntax_valid
    assert not interfaces_preserved


def test_rejects_invalid_syntax() -> None:
    with pytest.raises(SyntaxError):
        validate_candidate("value = 1\n", "def broken(:\n")
