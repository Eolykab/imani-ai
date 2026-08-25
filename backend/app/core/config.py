from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PiPilot"
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:1.5b"
    telegram_bot_token: str = ""
    telegram_allowed_user_ids: Annotated[list[int], NoDecode] = []
    database_url: str = "sqlite:///./data/pipilot.db"
    pipilot_allowed_services: Annotated[list[str], NoDecode] = ["pipilot", "ollama"]
    pipilot_upload_dir: Path = Path("./data/uploads")
    pipilot_max_upload_mb: int = 10
    frontend_dir: Path = Path("./frontend/dist")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def parse_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return value

    @field_validator("pipilot_allowed_services", mode="before")
    @classmethod
    def parse_services(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
