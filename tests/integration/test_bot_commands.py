"""Integration tests for bot commands (mocked Discord client)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blackstar_bot.audio_source import BlackstarAudioSource
from blackstar_bot.bot_sounddevice import stop, stream


def _make_ctx(*, in_voice=True, voice_client=None):
    """Create a mock ApplicationContext."""
    ctx = AsyncMock()
    if in_voice:
        ctx.author.voice.channel = AsyncMock()
        ctx.author.voice.channel.name = "General"
        ctx.author.voice.channel.connect = AsyncMock(return_value=voice_client or AsyncMock())
    else:
        ctx.author.voice = None
    ctx.voice_client = voice_client
    return ctx


def _mock_settings():
    """Create a mock Settings object."""
    s = MagicMock()
    s.audio_device = "Blackstar"
    s.volume = 1.0
    s.discord_token = "fake-token"
    return s


@pytest.mark.asyncio
async def test_stream_command_requires_voice_channel():
    """The /stream command should tell the user to join a voice channel first."""
    ctx = _make_ctx(in_voice=False)
    await stream(ctx)
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "must be in a voice channel" in args.lower()


@pytest.mark.asyncio
async def test_stop_command_when_not_connected():
    """The /stop command should respond gracefully when not in a channel."""
    ctx = _make_ctx(in_voice=True)
    ctx.voice_client = None
    await stop(ctx)
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "not currently in a voice channel" in args.lower()


@pytest.mark.asyncio
async def test_stream_command_device_not_found():
    """The /stream command should report when the audio device is not found."""
    ctx = _make_ctx(in_voice=True)
    with (
        patch("blackstar_bot.bot_sounddevice._get_settings", return_value=_mock_settings()),
        patch("blackstar_bot.bot_sounddevice.find_device_by_name", return_value=None),
    ):
        await stream(ctx)
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "not found" in args.lower()


@pytest.mark.asyncio
async def test_stop_command_disconnects_when_playing():
    """The /stop command should stop playback and disconnect."""
    vc = AsyncMock()
    vc.is_playing = MagicMock(return_value=True)
    vc.stop = MagicMock()

    ctx = _make_ctx(in_voice=True, voice_client=vc)
    await stop(ctx)

    vc.stop.assert_called_once()
    vc.disconnect.assert_awaited_once()
    ctx.respond.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_command_cleans_up_when_not_playing():
    """The /stop command should cleanup source when not playing but source exists."""
    mock_source = MagicMock(spec=BlackstarAudioSource)
    vc = AsyncMock()
    vc.is_playing = MagicMock(return_value=False)
    vc.source = mock_source

    ctx = _make_ctx(in_voice=True, voice_client=vc)
    await stop(ctx)

    mock_source.cleanup.assert_called_once()
    vc.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_command_already_connected():
    """The /stream command should reject when already streaming."""
    vc = AsyncMock()
    ctx = _make_ctx(in_voice=True, voice_client=vc)
    await stream(ctx)
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "already streaming" in args.lower()
