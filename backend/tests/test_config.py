from app.core.config import Settings


def test_comma_separated_environment_lists(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123456,789012")
    monkeypatch.setenv("PIPILOT_ALLOWED_SERVICES", "pipilot,ollama")
    settings = Settings(_env_file=None)
    assert settings.telegram_allowed_user_ids == [123456, 789012]
    assert settings.pipilot_allowed_services == ["pipilot", "ollama"]
