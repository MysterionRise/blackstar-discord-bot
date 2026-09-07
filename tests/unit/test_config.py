"""Tests for blackstar_bot.config."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from blackstar_bot.config import Settings

OWNER_ID = 424242424242424242


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch, tmp_path):
    """Keep a developer's real .env out of these tests."""
    monkeypatch.chdir(tmp_path)
    for key in ("DISCORD_TOKEN", "OWNER_ID", "GUILD_ID", "AUDIO_DEVICE", "LOG_FILE"):
        monkeypatch.delenv(key, raising=False)


def test_settings_defaults(monkeypatch):
    """Settings should load with sensible defaults when the required values are set."""
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("OWNER_ID", str(OWNER_ID))
    settings = Settings()
    assert settings.discord_token == "test-token"
    assert settings.owner_id == OWNER_ID
    assert settings.guild_id is None
    assert settings.audio_device == "Blackstar"
    assert settings.audio_backend == "sounddevice"
    assert settings.debug_config is False
    assert settings.log_file == Path("blackstar-bot.log")
    assert settings.volume == 1.0


def test_settings_custom_values(monkeypatch):
    """Settings should respect custom environment variables."""
    monkeypatch.setenv("DISCORD_TOKEN", "my-token")
    monkeypatch.setenv("OWNER_ID", str(OWNER_ID))
    monkeypatch.setenv("GUILD_ID", "123456789012345678")
    monkeypatch.setenv("AUDIO_DEVICE", "USB Audio")
    monkeypatch.setenv("AUDIO_BACKEND", "ffmpeg")
    monkeypatch.setenv("DEBUG_CONFIG", "true")
    monkeypatch.setenv("VOLUME", "0.8")
    settings = Settings()
    assert settings.guild_id == 123456789012345678
    assert settings.audio_device == "USB Audio"
    assert settings.audio_backend == "ffmpeg"
    assert settings.debug_config is True
    assert settings.volume == 0.8


def test_settings_requires_owner_id(monkeypatch):
    """The bot must fail closed rather than start with no owner configured."""
    monkeypatch.setenv("DISCORD_TOKEN", "my-token")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_non_positive_owner_id(monkeypatch):
    """Discord snowflakes are positive; anything else is a misconfiguration."""
    monkeypatch.setenv("DISCORD_TOKEN", "my-token")
    monkeypatch.setenv("OWNER_ID", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_blank_log_file_disables_file_logging(monkeypatch):
    """An empty LOG_FILE must mean "no file", not a path pointing at the cwd."""
    monkeypatch.setenv("DISCORD_TOKEN", "my-token")
    monkeypatch.setenv("OWNER_ID", str(OWNER_ID))
    monkeypatch.setenv("LOG_FILE", "   ")
    assert Settings().log_file is None


def test_settings_custom_log_file(monkeypatch):
    """LOG_FILE should be honoured when set."""
    monkeypatch.setenv("DISCORD_TOKEN", "my-token")
    monkeypatch.setenv("OWNER_ID", str(OWNER_ID))
    monkeypatch.setenv("LOG_FILE", "/tmp/blackstar.log")
    assert Settings().log_file == Path("/tmp/blackstar.log")
