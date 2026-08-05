from pydantic import BaseModel, Field


class RefactorProposal(BaseModel):
    code: str
    changes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    syntax_valid: bool
    interfaces_preserved: bool
    original_pylint_score: float | None = None
    refactored_pylint_score: float | None = None


class RefactorReport(BaseModel):
    source: str
    output: str
    llm_used: bool
    changes: list[str]
    warnings: list[str]
    validation: ValidationResult
