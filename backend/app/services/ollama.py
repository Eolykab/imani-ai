import time
from typing import Any

import httpx

from app.core.config import get_settings


class OllamaService:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.ollama_url.rstrip("/")
        self.model = settings.ollama_model

    async def status(self) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            models = [row.get("name", "") for row in response.json().get("models", [])]
            return {"online": True, "model": self.model, "model_ready": self.model in models, "models": models,
                    "response_ms": round((time.perf_counter() - start) * 1000)}
        except (httpx.HTTPError, ValueError) as exc:
            return {"online": False, "model": self.model, "model_ready": False, "models": [], "error": type(exc).__name__}

    async def chat(self, messages: list[dict[str, str]], *, format_json: bool = False) -> str:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if format_json:
            payload["format"] = "json"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
        return str(response.json()["message"]["content"])

