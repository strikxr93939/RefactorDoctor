import argparse
import sys
from pathlib import Path

from .config import Settings
from .service import RefactorService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refactor-doctor", description="Безопасная модернизация legacy Python-кода"
    )
    parser.add_argument("source", help="Путь к .py или '-' для чтения stdin")
    parser.add_argument("--output", type=Path, help="Путь для нового файла")
    parser.add_argument(
        "--in-place", action="store_true", help="Заменить исходник с .bak-копией"
    )
    parser.add_argument("--no-llm", action="store_true", help="Не обращаться к Ollama")
    parser.add_argument(
        "--docstring-style", choices=["google", "numpy"], default="google"
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.source == "-":
        code = sys.stdin.read()
        source_name = "stdin"
        output = args.output or Path("refactored.py")
    else:
        source = Path(args.source).resolve()
        if not source.is_file() or source.suffix.lower() != ".py":
            raise SystemExit("Источник должен быть существующим .py-файлом")
        code = source.read_text(encoding="utf-8-sig")
        source_name = str(source)
        if args.in_place:
            backup = source.with_suffix(source.suffix + ".bak")
            if backup.exists():
                raise SystemExit(f"Резервная копия уже существует: {backup}")
            backup.write_text(code, encoding="utf-8", newline="\n")
            output = source
        else:
            output = args.output or source.with_name(f"{source.stem}.refactored.py")
    settings = Settings()
    if args.no_llm:
        settings.use_llm = False
    try:
        report = RefactorService(settings).refactor(
            source_name, code, output, args.docstring_style
        )
    except (SyntaxError, ValueError) as exc:
        raise SystemExit(f"Рефакторинг отменён: {exc}") from exc
    print(report.model_dump_json(indent=2))
