import asyncio
import re
import shutil
from pathlib import Path
from typing import Any

from app.core.config import get_settings

STT_MODULE = "hailo_apps.python.standalone_apps.speech_recognition.speech_recognition"


class VoiceUnavailable(RuntimeError):
    pass


def extract_transcript(output: str) -> str:
    """Extract the transcript without treating diagnostic logs as user speech."""
    separated = re.findall(r"(?ms)^-{10,}\s*\n(.+?)\n-{10,}\s*(?:\n|$)", output)
    if separated:
        transcript = separated[-1].strip()
        if transcript:
            return transcript
    patterns = (
        r"(?im)^transcription\s*:\s*(.+)$",
        r"(?im)^transcript\s*:\s*(.+)$",
        r"(?im)^recognized text\s*:\s*(.+)$",
    )
    for pattern in patterns:
        matches = re.findall(pattern, output)
        if matches:
            return matches[-1].strip()
    clean = [line.strip() for line in output.splitlines() if line.strip()]
    candidates = [line for line in clean if not re.match(r"^(INFO|DEBUG|WARNING|ERROR|\[|Loading|Using|Model)", line, re.I)]
    if len(candidates) == 1:
        return candidates[0]
    raise VoiceUnavailable("Hailo completed but PiPilot could not identify the transcript in its output")


async def _run(command: list[str], timeout: int) -> tuple[str, str]:
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill(); await process.communicate()
        raise VoiceUnavailable("Voice processing timed out") from None
    if process.returncode != 0:
        lines = [line.strip() for line in stderr.decode(errors="replace").splitlines() if line.strip()]
        detail = lines[-1][:300] if lines else "unknown Hailo error"
        if "Failed to resolve model" in detail:
            raise VoiceUnavailable("Hailo Whisper model resources are missing; download the whisper_h8 resources")
        raise VoiceUnavailable(f"Voice processing failed: {detail}")
    return stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def transcribe_hailo_voice(source: Path, wav_path: Path) -> dict[str, Any]:
    settings = get_settings()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VoiceUnavailable("ffmpeg is not installed")
    python = settings.hailo_stt_python
    if not python.is_file():
        raise VoiceUnavailable(f"Hailo speech environment not found at {python}")
    await _run([ffmpeg, "-nostdin", "-y", "-i", str(source), "-ar", "16000", "-ac", "1", str(wav_path)], 30)
    stdout, _ = await _run([
        str(python), "-m", STT_MODULE, "--audio", str(wav_path),
        "--arch", "hailo8", "--variant", settings.hailo_stt_variant,
    ], 180)
    return {"text": extract_transcript(stdout), "engine": "Hailo-8 Whisper", "variant": settings.hailo_stt_variant}
