"""Integration tests for bot commands (mocked Discord client)."""

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blackstar_bot.audio_source import BlackstarAudioSource
from blackstar_bot.authz import UNAUTHORIZED_MESSAGE
from blackstar_bot.bot_sounddevice import devices, status, stop, stream, volume
from blackstar_bot.device_finder import AudioDevice

OWNER_ID = 424242424242424242
INTRUDER_ID = 999999999999999999


@pytest.fixture(autouse=True)
def reset_runtime_state():
    """Reset module-level command state between tests."""
    import blackstar_bot.bot_sounddevice as bot_module

    bot_module._volume_override = None
    bot_module._settings = _mock_settings()
    yield
    bot_module._volume_override = None
    bot_module._settings = None


def _make_ctx(*, in_voice=True, voice_client=None, author_id=OWNER_ID):
    """Create a mock ApplicationContext, owned by the configured owner by default."""
    ctx = AsyncMock()
    ctx.channel.send = AsyncMock()
    ctx.author = MagicMock()
    ctx.author.id = author_id
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
    s.owner_id = OWNER_ID
    s.guild_id = 123456789012345678
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


@pytest.mark.parametrize("command", [stream, stop, status, devices, volume])
@pytest.mark.asyncio
async def test_commands_reject_non_owner(command):
    """Every command must refuse anyone but the configured owner."""
    ctx = _make_ctx(in_voice=True, author_id=INTRUDER_ID)

    with (
        patch("blackstar_bot.bot_sounddevice.find_device_by_name") as find_device,
        patch("blackstar_bot.bot_sounddevice.list_input_devices") as list_devices,
    ):
        await command(ctx)

    ctx.respond.assert_awaited_once_with(UNAUTHORIZED_MESSAGE, ephemeral=True)
    ctx.author.voice.channel.connect.assert_not_awaited()
    find_device.assert_not_called()
    list_devices.assert_not_called()


def test_stream_command_does_not_accept_device_override():
    """/stream must expose no parameters that could select another input device."""
    assert [option.name for option in stream.options] == []
    assert list(inspect.signature(stream.callback).parameters) == ["ctx"]


@pytest.mark.asyncio
async def test_stream_command_uses_configured_device_only():
    """The streamed device always comes from configuration, never from the invoker."""
    vc = AsyncMock()
    vc.is_playing = MagicMock(return_value=False)
    vc.play = MagicMock()
    ctx = _make_ctx(in_voice=True)
    ctx.author.voice.channel.connect = AsyncMock(return_value=vc)
    settings = _mock_settings()
    settings.audio_device = "Blackstar"

    with (
        patch("blackstar_bot.bot_sounddevice._get_settings", return_value=settings),
        patch(
            "blackstar_bot.bot_sounddevice.find_device_by_name", return_value=_fake_device()
        ) as find_device,
        patch("blackstar_bot.bot_sounddevice.BlackstarAudioSource", return_value=MagicMock()),
    ):
        await stream(ctx)

    find_device.assert_called_once_with("Blackstar")


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
    settings.audio_backend = "ffmpeg"
    ffmpeg_source = MagicMock()

    with (
        patch("blackstar_bot.bot_sounddevice._get_settings", return_value=settings),
        patch("blackstar_bot.bot_sounddevice.discord.FFmpegPCMAudio", return_value=ffmpeg_source),
    ):
        await stream(ctx)

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


def _was_ephemeral(ctx):
    """Return whether the last response was sent privately to the invoker."""
    return ctx.respond.await_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_devices_command_replies_privately():
    """/devices lists local hardware, so it must never post to the channel."""
    ctx = _make_ctx(in_voice=True)
    with patch("blackstar_bot.bot_sounddevice.list_input_devices", return_value=[_fake_device()]):
        await devices(ctx)

    assert _was_ephemeral(ctx)


@pytest.mark.asyncio
async def test_status_command_replies_privately_when_streaming():
    """/status names the capture device, so it stays private."""
    vc = AsyncMock()
    vc.source = BlackstarAudioSource(_fake_device(), volume=1.0)
    ctx = _make_ctx(in_voice=True, voice_client=vc)
    await status(ctx)

    assert _was_ephemeral(ctx)


@pytest.mark.asyncio
async def test_volume_command_replies_privately():
    """/volume is informational and only the owner can run it."""
    ctx = _make_ctx(in_voice=True)
    await volume(ctx, level=0.5)

    assert _was_ephemeral(ctx)


@pytest.mark.asyncio
async def test_stream_failure_reply_is_private():
    """Failure text can carry local paths from the exception, so keep it private."""
    vc = AsyncMock()
    vc.is_playing = MagicMock(return_value=False)
    ctx = _make_ctx(in_voice=True)
    ctx.author.voice.channel.connect = AsyncMock(return_value=vc)
    source = MagicMock()
    source.start.side_effect = RuntimeError("/Users/someone/secret path")

    with (
        patch("blackstar_bot.bot_sounddevice.find_device_by_name", return_value=_fake_device()),
        patch("blackstar_bot.bot_sounddevice.BlackstarAudioSource", return_value=source),
    ):
        await stream(ctx)

    assert _was_ephemeral(ctx)


@pytest.mark.asyncio
async def test_successful_stream_and_stop_stay_public():
    """Voice-channel members should see that a stream started and ended."""
    vc = AsyncMock()
    vc.is_playing = MagicMock(return_value=False)
    vc.play = MagicMock()
    ctx = _make_ctx(in_voice=True)
    ctx.author.voice.channel.connect = AsyncMock(return_value=vc)

    with (
        patch("blackstar_bot.bot_sounddevice.find_device_by_name", return_value=_fake_device()),
        patch("blackstar_bot.bot_sounddevice.BlackstarAudioSource", return_value=MagicMock()),
    ):
        await stream(ctx)
    assert not _was_ephemeral(ctx)

    stop_ctx = _make_ctx(in_voice=True, voice_client=vc)
    await stop(stop_ctx)
    assert not _was_ephemeral(stop_ctx)


def test_playback_failure_notice_omits_exception_detail():
    """The channel-wide failure notice must not leak exception text."""
    import blackstar_bot.bot_sounddevice as bot_module

    captured = []

    async def _noop():
        return None

    def _fake_send(_ctx, message):
        captured.append(message)
        return _noop()

    with (
        patch.object(bot_module, "_send_channel_message", _fake_send),
        patch.object(bot_module, "bot") as fake_bot,
    ):
        fake_bot.loop.create_task = lambda coro: coro.close()
        bot_module._after_playback(_make_ctx(), None, RuntimeError("/Users/someone/secret path"))

    assert captured, "expected a channel notice"
    assert "secret path" not in captured[0]
    assert "see the bot log" in captured[0]


@pytest.mark.parametrize("command", [stream, stop])
@pytest.mark.asyncio
async def test_slow_commands_defer_before_working(command):
    """Voice work outlasts Discord's 3s deadline, so the interaction is acknowledged first."""
    ctx = _make_ctx(in_voice=True)
    with (
        patch("blackstar_bot.bot_sounddevice.find_device_by_name", return_value=None),
        patch("blackstar_bot.bot_sounddevice._connect_with_retry"),
    ):
        await command(ctx)

    ctx.defer.assert_awaited_once_with(ephemeral=True)


@pytest.mark.asyncio
async def test_stream_defers_before_connecting():
    """The defer must happen before the voice handshake, not after it."""
    ctx = _make_ctx(in_voice=True)
    order = []
    ctx.defer = AsyncMock(side_effect=lambda **_: order.append("defer"))

    async def _connect(_channel):
        order.append("connect")
        vc = AsyncMock()
        vc.play = MagicMock()
        return vc

    with (
        patch("blackstar_bot.bot_sounddevice.find_device_by_name", return_value=_fake_device()),
        patch("blackstar_bot.bot_sounddevice._connect_with_retry", _connect),
        patch("blackstar_bot.bot_sounddevice.BlackstarAudioSource", return_value=MagicMock()),
    ):
        await stream(ctx)

    assert order == ["defer", "connect"]


@pytest.mark.asyncio
async def test_non_owner_is_refused_without_deferring():
    """An unauthorized caller gets an immediate refusal, not a "thinking" state."""
    ctx = _make_ctx(in_voice=True, author_id=INTRUDER_ID)
    await stream(ctx)

    ctx.defer.assert_not_awaited()
    ctx.respond.assert_awaited_once_with(UNAUTHORIZED_MESSAGE, ephemeral=True)
