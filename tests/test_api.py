from fastapi.testclient import TestClient

from refactor_doctor.api import create_app
from refactor_doctor.config import Settings


def test_refactors_pasted_code_without_upload() -> None:
    with TestClient(create_app(Settings(use_llm=False))) as client:
        response = client.post(
            "/api/v1/refactor",
            data={
                "source_code": "def greet(name):\n    print('Hello', name)\n",
                "source_name": "legacy_greeting",
                "docstring_style": "google",
                "use_llm": "false",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "legacy_greeting.refactored.py"
    assert "logger.info" in payload["refactored_code"]
    assert payload["report"]["validation"]["interfaces_preserved"] is True


def test_refactor_requires_file_or_pasted_code() -> None:
    with TestClient(create_app(Settings(use_llm=False))) as client:
        response = client.post(
            "/api/v1/refactor",
            data={"docstring_style": "google", "use_llm": "false"},
        )

    assert response.status_code == 422
    assert "Загрузите" in response.json()["detail"]


def test_syntax_error_points_to_bad_line_and_explains_backslash() -> None:
    with TestClient(create_app(Settings(use_llm=False))) as client:
        response = client.post(
            "/api/v1/refactor",
            data={
                "source_code": "value = 1\\nnext_value = 2",
                "use_llm": "false",
            },
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "syntax_error"
    assert detail["line"] == 1
    assert "line continuation character" in detail["reason"]
    assert "переносами" in detail["hint"]
