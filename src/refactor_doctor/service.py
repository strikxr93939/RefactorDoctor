import ast
import re
from pathlib import Path

import black
import httpx
from langchain_ollama import ChatOllama

from .config import Settings
from .models import RefactorProposal, RefactorReport, ValidationResult
from .transformer import transform_legacy_code
from .validation import pylint_score, validate_candidate

PROMPT = """Ты senior Python-разработчик. Улучши уже синтаксически корректный код:
сохрани публичные имена, сигнатуры и поведение; добавь точные type hints и
docstrings; используй pathlib и logging; устрани Pylint-проблемы. Не добавляй
новую бизнес-логику и зависимости. Верни только структурированный результат.
"""


def _strip_fence(code: str) -> str:
    match = re.fullmatch(r"\s*```(?:python)?\s*(.*?)\s*```\s*", code, re.DOTALL)
    return match.group(1) if match else code


class RefactorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _llm_available(self) -> bool:
        if not self.settings.use_llm:
            return False
        try:
            return httpx.get(
                f"{self.settings.ollama_base_url}/api/tags", timeout=2
            ).is_success
        except httpx.HTTPError:
            return False

    def refactor(
        self,
        source_name: str,
        code: str,
        output: Path,
        docstring_style: str = "google",
    ) -> RefactorReport:
        ast.parse(code)
        candidate, changes = transform_legacy_code(code, docstring_style)
        warnings: list[str] = []
        llm_used = False

        if self._llm_available():
            model = ChatOllama(
                base_url=self.settings.ollama_base_url,
                model=self.settings.ollama_model,
                temperature=0,
                client_kwargs={"timeout": self.settings.ollama_timeout_seconds},
            ).with_structured_output(RefactorProposal)
            try:
                proposal = model.invoke([("system", PROMPT), ("human", candidate)])
                if not isinstance(proposal, RefactorProposal):
                    proposal = RefactorProposal.model_validate(proposal)
                proposed_code = _strip_fence(proposal.code)
                _, interfaces_preserved = validate_candidate(code, proposed_code)
                if interfaces_preserved:
                    candidate = proposed_code
                    changes.extend(proposal.changes)
                    warnings.extend(proposal.risks)
                    llm_used = True
                else:
                    warnings.append(
                        "Вариант Ollama отклонён: изменён публичный интерфейс"
                    )
            except Exception as exc:  # noqa: BLE001 - validated fallback is intentional
                warnings.append(f"Ollama недоступна или вернула неверный код: {exc}")
        elif self.settings.use_llm:
            warnings.append("Ollama не запущена — применён детерминированный AST-режим")

        candidate = black.format_str(candidate, mode=black.Mode())
        syntax_valid, interfaces_preserved = validate_candidate(code, candidate)
        if not interfaces_preserved:
            raise ValueError("Рефакторинг изменил сигнатуры функций")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(candidate, encoding="utf-8", newline="\n")
        original_score = pylint_score(code)
        refactored_score = pylint_score(candidate)
        if refactored_score is not None and refactored_score < 9:
            warnings.append(
                f"Pylint {refactored_score:.2f}/10 ниже целевого 9/10; требуется ручная проверка"
            )
        return RefactorReport(
            source=source_name,
            output=str(output.resolve()),
            llm_used=llm_used,
            changes=list(dict.fromkeys(changes)),
            warnings=warnings,
            validation=ValidationResult(
                syntax_valid=syntax_valid,
                interfaces_preserved=interfaces_preserved,
                original_pylint_score=original_score,
                refactored_pylint_score=refactored_score,
            ),
        )
