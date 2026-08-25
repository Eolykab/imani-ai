import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def parse_reminder_time(value: str) -> datetime:
    """Parse a small, predictable set of reminder expressions into naive UTC."""
    text = value.strip().lower()
    now_local = datetime.now(ZoneInfo(get_settings().pipilot_timezone))
    relative = re.fullmatch(r"in\s+(\d+)\s+(minute|minutes|hour|hours|day|days)", text)
    if relative:
        amount = int(relative.group(1)); unit = relative.group(2)
        delta = timedelta(minutes=amount) if unit.startswith("minute") else timedelta(hours=amount) if unit.startswith("hour") else timedelta(days=amount)
        return (now_local + delta).astimezone(timezone.utc).replace(tzinfo=None)
    day_match = re.fullmatch(r"(today|tomorrow)(?:\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?", text)
    if day_match:
        hour = int(day_match.group(2) or 9); minute = int(day_match.group(3) or 0); meridiem = day_match.group(4)
        if meridiem == "pm" and hour < 12: hour += 12
        if meridiem == "am" and hour == 12: hour = 0
        target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day_match.group(1) == "tomorrow": target += timedelta(days=1)
        return target.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=ZoneInfo(get_settings().pipilot_timezone))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError as exc:
        raise ValueError("Use 'tomorrow at 9', 'in 30 minutes', or an ISO date/time") from exc


def display_local(value: datetime) -> str:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(ZoneInfo(get_settings().pipilot_timezone)).strftime("%Y-%m-%d %H:%M %Z")
