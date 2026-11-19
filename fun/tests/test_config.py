import pytest

from backend.config import load_settings


def test_load_settings_parses_optional_turn_configuration(monkeypatch) -> None:
    monkeypatch.setenv("TURN_URLS", "turn:relay.example:3478,turns:relay.example:5349")
    monkeypatch.setenv("TURN_USERNAME", "short-lived-user")
    monkeypatch.setenv("TURN_CREDENTIAL", "short-lived-credential")

    settings = load_settings()

    assert settings.turn_urls == (
        "turn:relay.example:3478",
        "turns:relay.example:5349",
    )
    assert settings.turn_username == "short-lived-user"
    assert settings.turn_credential == "short-lived-credential"


def test_load_settings_requires_complete_turn_configuration(monkeypatch) -> None:
    monkeypatch.setenv("TURN_URLS", "turn:relay.example:3478")
    monkeypatch.setenv("TURN_USERNAME", "short-lived-user")
    monkeypatch.delenv("TURN_CREDENTIAL", raising=False)

    with pytest.raises(RuntimeError, match="Configure TURN_URLS"):
        load_settings()


def test_load_settings_rejects_non_turn_urls(monkeypatch) -> None:
    monkeypatch.setenv("TURN_URLS", "stun:relay.example:3478")
    monkeypatch.setenv("TURN_USERNAME", "short-lived-user")
    monkeypatch.setenv("TURN_CREDENTIAL", "short-lived-credential")

    with pytest.raises(RuntimeError, match="only turn: or turns:"):
        load_settings()


def test_cookie_secure_setting_can_be_enabled_for_https(monkeypatch) -> None:
    monkeypatch.setenv("COOKIE_SECURE", "true")

    assert load_settings().cookie_secure is True
