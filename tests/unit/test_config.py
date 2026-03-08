"""Tests for blackstar_bot.config."""

from blackstar_bot.config import Settings


def test_settings_defaults(monkeypatch):
    """Settings should load with sensible defaults when DISCORD_TOKEN is set."""
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    settings = Settings()
    assert settings.discord_token == "test-token"
    assert settings.audio_device == "Blackstar"
    assert settings.audio_device_index is None
    assert settings.volume == 1.0


def test_settings_custom_values(monkeypatch):
    """Settings should respect custom environment variables."""
    monkeypatch.setenv("DISCORD_TOKEN", "my-token")
    monkeypatch.setenv("AUDIO_DEVICE", "USB Audio")
    monkeypatch.setenv("AUDIO_DEVICE_INDEX", "3")
    monkeypatch.setenv("VOLUME", "0.8")
    settings = Settings()
    assert settings.audio_device == "USB Audio"
    assert settings.audio_device_index == 3
    assert settings.volume == 0.8
