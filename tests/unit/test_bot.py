"""Tests for guitar_amp_bot.bot_sounddevice helpers."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

import guitar_amp_bot.bot_sounddevice as bot_module
from guitar_amp_bot.bot_sounddevice import (
    _connect_with_retry,
    _ffmpeg_input_args,
    _format_device_list,
    _resolve_guild_ids,
    main,
    on_ready,
)
from guitar_amp_bot.device_finder import AudioDevice


def test_ffmpeg_input_args_darwin():
    with patch("guitar_amp_bot.bot_sounddevice.sys") as mock_sys:
        mock_sys.platform = "darwin"
        source, opts = _ffmpeg_input_args("MyDevice")
    assert source == ":MyDevice"
    assert "avfoundation" in opts


def test_ffmpeg_input_args_linux():
    with patch("guitar_amp_bot.bot_sounddevice.sys") as mock_sys:
        mock_sys.platform = "linux"
        source, opts = _ffmpeg_input_args("MyDevice")
    assert source == "hw:MyDevice"
    assert "alsa" in opts


def test_ffmpeg_input_args_win32():
    with patch("guitar_amp_bot.bot_sounddevice.sys") as mock_sys:
        mock_sys.platform = "win32"
        source, opts = _ffmpeg_input_args("MyDevice")
    assert source == "audio=MyDevice"
    assert "dshow" in opts


def test_resolve_guild_ids_scopes_commands_to_configured_guild():
    settings = MagicMock()
    settings.guild_id = 123456789012345678
    with patch("guitar_amp_bot.bot_sounddevice._get_settings", return_value=settings):
        assert _resolve_guild_ids() == [123456789012345678]


def test_resolve_guild_ids_returns_none_when_unset():
    settings = MagicMock()
    settings.guild_id = None
    with patch("guitar_amp_bot.bot_sounddevice._get_settings", return_value=settings):
        assert _resolve_guild_ids() is None


def test_resolve_guild_ids_tolerates_unreadable_settings():
    """Import-time evaluation must not raise when the environment is incomplete."""
    error = ValidationError.from_exception_data("Settings", [])
    with patch("guitar_amp_bot.bot_sounddevice._get_settings", side_effect=error):
        assert _resolve_guild_ids() is None


def test_format_device_list_handles_empty_list():
    assert _format_device_list([]) == "No audio input devices were detected."


def test_format_device_list_includes_device_details():
    device = AudioDevice(
        index=1,
        name="Blackstar ID:Core V4",
        max_input_channels=2,
        default_samplerate=48000.0,
    )
    output = _format_device_list([device])
    assert "Blackstar ID:Core V4" in output
    assert "2 input channels" in output
    assert "48000 Hz" in output


def test_suite_is_isolated_from_local_configuration():
    """A developer's .env or exported GUILD_ID must not scope the commands under test."""
    assert bot_module.GUILD_IDS is None


GUILD_ID = 123456789012345678


def _run_main(monkeypatch, *, guild_id, guild_ids):
    settings = MagicMock(guild_id=guild_id, discord_token="fake-token")
    fake_bot = MagicMock()
    monkeypatch.setattr(bot_module, "_get_settings", lambda: settings)
    monkeypatch.setattr(bot_module, "configure_logging", MagicMock())
    monkeypatch.setattr(bot_module, "bot", fake_bot)
    monkeypatch.setattr(bot_module, "GUILD_IDS", guild_ids)
    main()
    bot_module.configure_logging.assert_called_once_with(settings)
    fake_bot.run.assert_called_once_with("fake-token")


def _logged(caplog):
    return [record.getMessage() for record in caplog.records]


def test_main_says_commands_are_global_without_guild_id(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="guitar_amp_bot.bot_sounddevice"):
        _run_main(monkeypatch, guild_id=None, guild_ids=None)

    assert any(message.startswith("guild_scope_global") for message in _logged(caplog))


def test_main_warns_when_guild_id_was_unreadable_at_registration(monkeypatch, caplog):
    """GUILD_ID set now but not at import means commands went out globally."""
    with caplog.at_level(logging.INFO, logger="guitar_amp_bot.bot_sounddevice"):
        _run_main(monkeypatch, guild_id=GUILD_ID, guild_ids=None)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(r.getMessage().startswith("guild_scope_unavailable") for r in warnings)


def test_main_is_quiet_about_scope_when_commands_are_guild_scoped(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="guitar_amp_bot.bot_sounddevice"):
        _run_main(monkeypatch, guild_id=GUILD_ID, guild_ids=[GUILD_ID])

    assert not any(message.startswith("guild_scope") for message in _logged(caplog))


async def test_on_ready_logs_in_and_announces_startup(monkeypatch, caplog):
    settings = MagicMock()
    fake_bot = MagicMock()
    fake_bot.user.id = 555555555555555555
    announce = AsyncMock()
    monkeypatch.setattr(bot_module, "bot", fake_bot)
    monkeypatch.setattr(bot_module, "_get_settings", lambda: settings)
    monkeypatch.setattr(bot_module, "announce_startup", announce)

    with caplog.at_level(logging.INFO, logger="guitar_amp_bot.bot_sounddevice"):
        await on_ready()

    announce.assert_awaited_once_with(fake_bot, settings)
    assert any("555555555555555555" in message for message in _logged(caplog))


@pytest.fixture
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(bot_module, "CONNECT_RETRY_DELAY_SECONDS", 0)


async def test_connect_retries_after_a_failed_attempt(no_retry_delay):
    voice_client = MagicMock()
    channel = MagicMock()
    channel.connect = AsyncMock(side_effect=[RuntimeError("handshake failed"), voice_client])

    assert await _connect_with_retry(channel) is voice_client
    assert channel.connect.await_count == 2


async def test_connect_gives_up_with_the_last_error(no_retry_delay):
    channel = MagicMock()
    errors = [RuntimeError(f"attempt {n}") for n in range(1, bot_module.CONNECT_ATTEMPTS + 1)]
    channel.connect = AsyncMock(side_effect=errors)

    with pytest.raises(RuntimeError, match=f"attempt {bot_module.CONNECT_ATTEMPTS}"):
        await _connect_with_retry(channel)

    assert channel.connect.await_count == bot_module.CONNECT_ATTEMPTS


async def test_connect_without_any_attempt_raises(monkeypatch):
    monkeypatch.setattr(bot_module, "CONNECT_ATTEMPTS", 0)
    channel = MagicMock()
    channel.connect = AsyncMock()

    with pytest.raises(RuntimeError, match="without an exception"):
        await _connect_with_retry(channel)

    channel.connect.assert_not_awaited()
