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
    pipilot_voice_max_seconds: int = 60
    hailo_stt_python: Path = Path("/opt/hailo-apps/venv/bin/python")
    hailo_stt_variant: str = "tiny"
    pipilot_timezone: str = "Africa/Johannesburg"
    pipilot_daily_briefing_hour: int = 7
    pipilot_weather_location: str = ""
    pipilot_weather_latitude: float | None = None
    pipilot_weather_longitude: float | None = None
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

    @field_validator("pipilot_weather_latitude", "pipilot_weather_longitude", mode="before")
    @classmethod
    def empty_coordinate(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
