"""Tests for blackstar_bot.bot helpers."""

from unittest.mock import patch

from blackstar_bot.bot import _ffmpeg_input_args


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


def test_ffmpeg_input_args_other():
    with patch("blackstar_bot.bot.sys") as mock_sys:
        mock_sys.platform = "win32"
        source, opts = _ffmpeg_input_args("MyDevice")
    assert source == "MyDevice"
    assert "pulse" in opts
