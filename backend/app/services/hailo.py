import asyncio
import platform
import re
import shutil
from typing import Any


async def hailo_status() -> dict[str, Any]:
    base = {"detected": False, "device": None, "firmware": None, "architecture": None,
            "status": "not_available", "message": "Unavailable in development environment"}
    if platform.system() != "Linux":
        return base
    executable = shutil.which("hailortcli")
    if not executable:
        return {**base, "message": "hailortcli is not installed"}
    try:
        process = await asyncio.create_subprocess_exec(
            executable, "fw-control", "identify", stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=8)
    except (OSError, asyncio.TimeoutError) as exc:
        return {**base, "message": f"Detection failed: {type(exc).__name__}"}
    output = stdout.decode(errors="replace")
    if process.returncode != 0:
        return {**base, "message": stderr.decode(errors="replace").strip()[:300] or "Hailo device unavailable"}

    def match(label: str) -> str | None:
        result = re.search(rf"{label}\s*:\s*(.+)", output, re.IGNORECASE)
        return result.group(1).strip() if result else None

    return {"detected": True, "device": match("Device Architecture") or "Hailo-8",
            "firmware": match("Firmware Version"), "architecture": match("Device Architecture"),
            "status": "connected", "message": "Hailo accelerator detected (not used by Ollama)"}

