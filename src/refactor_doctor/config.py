from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="REFACTOR_", extra="ignore"
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    use_llm: bool = True
    ollama_timeout_seconds: int = Field(default=120, ge=10, le=600)
