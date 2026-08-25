from datetime import datetime, timezone

from app.services.reminders import parse_reminder_time


def test_relative_reminder_time_is_future():
    value = parse_reminder_time("in 30 minutes")
    assert value > datetime.now(timezone.utc).replace(tzinfo=None)


def test_tomorrow_expression_is_supported():
    value = parse_reminder_time("tomorrow at 9")
    assert value > datetime.now(timezone.utc).replace(tzinfo=None)
