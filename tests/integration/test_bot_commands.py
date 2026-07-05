"""Integration tests for bot commands (mocked Discord client)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blackstar_bot.audio_source import BlackstarAudioSource
from blackstar_bot.bot_sounddevice import devices, status, stop, stream, volume
from blackstar_bot.device_finder import AudioDevice


@pytest.fixture(autouse=True)
def reset_runtime_state():
    """Reset module-level command state between tests."""
    import blackstar_bot.bot_sounddevice as bot_module

    bot_module._volume_override = None
    yield
    bot_module._volume_override = None


def _make_ctx(*, in_voice=True, voice_client=None):
    """Create a mock ApplicationContext."""
    ctx = AsyncMock()
    ctx.channel.send = AsyncMock()
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
    s.audio_backend = "sounddevice"
    s.debug_config = False
    s.volume = 1.0
    s.discord_token = "fake-token"
    return s


def _fake_device() -> AudioDevice:
    return AudioDevice(
        index=5,
        name="Blackstar ID:Core V4",
        max_input_channels=2,
        default_samplerate=48000.0,
    )


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
    assert "/devices" in args


@pytest.mark.asyncio
async def test_stream_command_rejects_unknown_backend():
    """The /stream command should validate explicit backend choices."""
    ctx = _make_ctx(in_voice=True)
    with patch("blackstar_bot.bot_sounddevice._get_settings", return_value=_mock_settings()):
        await stream(ctx, backend="unknown")
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "unknown backend" in args.lower()


@pytest.mark.asyncio
async def test_stream_command_disconnects_when_source_start_fails():
    """Failed startup should clean up the partially connected voice client."""
    vc = AsyncMock()
    vc.is_playing = MagicMock(return_value=False)
    ctx = _make_ctx(in_voice=True)
    ctx.author.voice.channel.connect = AsyncMock(return_value=vc)
    source = MagicMock()
    source.start.side_effect = RuntimeError("bad sample rate")

    with (
        patch("blackstar_bot.bot_sounddevice._get_settings", return_value=_mock_settings()),
        patch("blackstar_bot.bot_sounddevice.find_device_by_name", return_value=_fake_device()),
        patch("blackstar_bot.bot_sounddevice.BlackstarAudioSource", return_value=source),
    ):
        await stream(ctx)

    source.cleanup.assert_called_once()
    vc.disconnect.assert_awaited_once()
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "could not start streaming" in args.lower()


@pytest.mark.asyncio
async def test_stream_command_starts_sounddevice_stream():
    """The /stream command should start the primary sounddevice backend."""
    vc = AsyncMock()
    vc.is_playing = MagicMock(return_value=False)
    vc.play = MagicMock()
    ctx = _make_ctx(in_voice=True)
    ctx.author.voice.channel.connect = AsyncMock(return_value=vc)
    source = MagicMock()

    with (
        patch("blackstar_bot.bot_sounddevice._get_settings", return_value=_mock_settings()),
        patch("blackstar_bot.bot_sounddevice.find_device_by_name", return_value=_fake_device()),
        patch("blackstar_bot.bot_sounddevice.BlackstarAudioSource", return_value=source),
    ):
        await stream(ctx)

    source.start.assert_called_once()
    vc.play.assert_called_once()
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "streaming audio" in args.lower()


@pytest.mark.asyncio
async def test_stream_command_starts_ffmpeg_backend():
    """The /stream command should support FFmpeg as an explicit fallback backend."""
    vc = AsyncMock()
    vc.is_playing = MagicMock(return_value=False)
    vc.play = MagicMock()
    ctx = _make_ctx(in_voice=True)
    ctx.author.voice.channel.connect = AsyncMock(return_value=vc)
    settings = _mock_settings()
    ffmpeg_source = MagicMock()

    with (
        patch("blackstar_bot.bot_sounddevice._get_settings", return_value=settings),
        patch("blackstar_bot.bot_sounddevice.discord.FFmpegPCMAudio", return_value=ffmpeg_source),
    ):
        await stream(ctx, backend="ffmpeg")

    vc.play.assert_called_once_with(
        ffmpeg_source,
        signal_type="music",
        after=vc.play.call_args.kwargs["after"],
    )
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "via ffmpeg" in args.lower()


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


@pytest.mark.asyncio
async def test_devices_command_lists_detected_inputs():
    """The /devices command should format available input devices."""
    ctx = _make_ctx(in_voice=True)
    with patch("blackstar_bot.bot_sounddevice.list_input_devices", return_value=[_fake_device()]):
        await devices(ctx)

    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "Blackstar ID:Core V4" in args
    assert "48000" in args


@pytest.mark.asyncio
async def test_status_command_when_not_streaming():
    """The /status command should report an idle bot."""
    ctx = _make_ctx(in_voice=True)
    ctx.voice_client = None
    await status(ctx)
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "not streaming" in args.lower()


@pytest.mark.asyncio
async def test_status_command_reports_active_sounddevice_source():
    """The /status command should describe an active sounddevice stream."""
    source = BlackstarAudioSource(_fake_device(), volume=0.75)
    vc = AsyncMock()
    vc.source = source
    ctx = _make_ctx(in_voice=True, voice_client=vc)
    await status(ctx)
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "Blackstar ID:Core V4" in args
    assert "0.75" in args


@pytest.mark.asyncio
async def test_volume_command_rejects_out_of_range_value():
    """The /volume command should validate user input."""
    ctx = _make_ctx(in_voice=True)
    with patch("blackstar_bot.bot_sounddevice._get_settings", return_value=_mock_settings()):
        await volume(ctx, level=5.1)
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "between" in args.lower()


@pytest.mark.asyncio
async def test_volume_command_updates_active_source():
    """The /volume command should update active sounddevice streams."""
    source = BlackstarAudioSource(_fake_device(), volume=1.0)
    vc = AsyncMock()
    vc.source = source
    ctx = _make_ctx(in_voice=True, voice_client=vc)

    with patch("blackstar_bot.bot_sounddevice._get_settings", return_value=_mock_settings()):
        await volume(ctx, level=0.4)

    assert source.volume == 0.4
    ctx.respond.assert_awaited_once()
    args = ctx.respond.await_args[0][0]
    assert "active stream" in args.lower()
