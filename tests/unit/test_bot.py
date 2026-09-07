"""Tests for blackstar_bot.bot helpers."""

from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from blackstar_bot.bot import _ffmpeg_input_args
from blackstar_bot.bot_sounddevice import _format_device_list, _resolve_guild_ids
from blackstar_bot.device_finder import AudioDevice


def test_ffmpeg_input_args_darwin():
    with patch("blackstar_bot.bot.sys") as mock_sys:
        mock_sys.platform = "darwin"
        source, opts = _ffmpeg_input_args("MyDevice")
    assert source == ":MyDevice"
    assert "avfoundation" in opts


def test_ffmpeg_input_args_linux():
    with patch("blackstar_bot.bot.sys") as mock_sys:
        mock_sys.platform = "linux"
        source, opts = _ffmpeg_input_args("MyDevice")
    assert source == "hw:MyDevice"
    assert "alsa" in opts


def test_ffmpeg_input_args_win32():
    with patch("blackstar_bot.bot.sys") as mock_sys:
        mock_sys.platform = "win32"
        source, opts = _ffmpeg_input_args("MyDevice")
    assert source == "audio=MyDevice"
    assert "dshow" in opts


def test_resolve_guild_ids_scopes_commands_to_configured_guild():
    settings = MagicMock()
    settings.guild_id = 123456789012345678
    with patch("blackstar_bot.bot_sounddevice._get_settings", return_value=settings):
        assert _resolve_guild_ids() == [123456789012345678]


def test_resolve_guild_ids_returns_none_when_unset():
    settings = MagicMock()
    settings.guild_id = None
    with patch("blackstar_bot.bot_sounddevice._get_settings", return_value=settings):
        assert _resolve_guild_ids() is None


def test_resolve_guild_ids_tolerates_unreadable_settings():
    """Import-time evaluation must not raise when the environment is incomplete."""
    error = ValidationError.from_exception_data("Settings", [])
    with patch("blackstar_bot.bot_sounddevice._get_settings", side_effect=error):
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
