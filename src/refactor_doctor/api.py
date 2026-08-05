import asyncio
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from .config import Settings
from .service import RefactorService
from .ui import HTML

MAX_SOURCE_BYTES = 2 * 1024 * 1024


async def _read_source(file: UploadFile) -> str:
    data = await file.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise HTTPException(status_code=413, detail="Python-файл превышает 2 МБ")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=422, detail="Исходник должен быть в UTF-8"
        ) from exc


def _read_pasted_source(source_code: str) -> str:
    code = source_code.lstrip("\ufeff")
    if len(code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise HTTPException(status_code=413, detail="Python-код превышает 2 МБ")
    if not code.strip():
        raise HTTPException(status_code=422, detail="Вставьте Python-код")
    return code


def _syntax_error_detail(exc: SyntaxError, code: str) -> dict[str, object]:
    line_number = exc.lineno or 1
    column = exc.offset or 1
    lines = code.splitlines()
    source_line = lines[line_number - 1] if line_number <= len(lines) else ""
    if "line continuation character" in exc.msg:
        hint = (
            "Проверьте обратный слеш \\: после него должен сразу идти перенос "
            "строки. Если в коде видны символы \\n, замените их настоящими "
            "переносами."
        )
    else:
        hint = "Исправьте эту строку в исходнике и запустите проверку ещё раз."
    return {
        "kind": "syntax_error",
        "message": "В исходном Python-коде синтаксическая ошибка",
        "reason": exc.msg,
        "line": line_number,
        "column": column,
        "source_line": source_line,
        "hint": hint,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Refactor Doctor", version="0.1.0")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index() -> str:
        return HTML

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"status": "ok", "llm_enabled": settings.use_llm}

    @app.post("/api/v1/refactor")
    async def refactor(
        file: Annotated[UploadFile | None, File()] = None,
        source_code: Annotated[str | None, Form()] = None,
        source_name: Annotated[str, Form()] = "pasted_code.py",
        docstring_style: Annotated[Literal["google", "numpy"], Form()] = "google",
        use_llm: Annotated[bool, Form()] = True,
    ) -> dict[str, object]:
        if file is not None and file.filename:
            filename = Path(file.filename).name
            if Path(filename).suffix.lower() != ".py":
                raise HTTPException(
                    status_code=422,
                    detail="Выберите Python-файл с расширением .py",
                )
            code = await _read_source(file)
        elif source_code is not None:
            code = _read_pasted_source(source_code)
            filename = Path(source_name).name or "pasted_code.py"
            if Path(filename).suffix.lower() != ".py":
                filename = f"{Path(filename).stem or 'pasted_code'}.py"
        else:
            raise HTTPException(
                status_code=422,
                detail="Загрузите .py-файл или вставьте Python-код",
            )
        run_settings = settings.model_copy(
            update={"use_llm": settings.use_llm and use_llm}
        )
        with tempfile.TemporaryDirectory(prefix="refactor-doctor-web-") as raw:
            output = Path(raw) / f"{Path(filename).stem}.refactored.py"
            try:
                report = await asyncio.to_thread(
                    RefactorService(run_settings).refactor,
                    filename,
                    code,
                    output,
                    docstring_style,
                )
            except SyntaxError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=_syntax_error_detail(exc, code),
                ) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {
                "report": report.model_dump(),
                "filename": output.name,
                "original_code": code,
                "refactored_code": output.read_text(encoding="utf-8"),
            }

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("refactor_doctor.api:app", host="127.0.0.1", port=8004)
