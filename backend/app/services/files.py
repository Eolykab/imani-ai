import json
import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings

ALLOWED_EXTENSIONS = {".txt", ".md", ".json", ".log"}


def safe_filename(name: str) -> str:
    base = Path(name).name
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")
    return safe[:180] or "upload.txt"


async def save_upload(upload: UploadFile) -> tuple[str, str, int]:
    settings = get_settings()
    original = safe_filename(upload.filename or "upload.txt")
    extension = Path(original).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file type")
    limit = settings.pipilot_max_upload_mb * 1024 * 1024
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise ValueError("File exceeds configured size limit")
    try:
        text = data.decode("utf-8")
        if extension == ".json":
            json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("File must contain valid UTF-8 text") from exc
    settings.pipilot_upload_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{extension}"
    (settings.pipilot_upload_dir / stored).write_bytes(data)
    return original, stored, len(data)


def read_controlled_file(stored_name: str, max_chars: int = 30000) -> str:
    directory = get_settings().pipilot_upload_dir.resolve()
    path = (directory / Path(stored_name).name).resolve()
    if path.parent != directory:
        raise ValueError("Invalid file")
    return path.read_text(encoding="utf-8")[:max_chars]

