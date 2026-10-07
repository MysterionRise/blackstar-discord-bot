"""Integration tests for the one-stream-per-instance rule across servers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import guitar_amp_bot.bot_sounddevice as bot_module
from guitar_amp_bot.audio_source import DeviceAudioSource
from guitar_amp_bot.bot_sounddevice import status, stop, stream, volume

OWNER_ID = 424242424242424242
STREAM_GUILD_ID = 123456789012345678
OTHER_GUILD_ID = 876543210987654321


@pytest.fixture(autouse=True)
def runtime_state(monkeypatch):
    settings = MagicMock()
    settings.owner_id = OWNER_ID
    settings.audio_backend = "sounddevice"
    settings.audio_device = "Blackstar"
    settings.input_channels = (1, 2)
    settings.debug_config = False
    settings.volume = 1.0
    monkeypatch.setattr(bot_module, "_settings", settings)
    monkeypatch.setattr(bot_module, "_volume_override", None)
    monkeypatch.setattr(bot_module, "_stream_starting", False)
    # The owner is in the stream's channel, so auto-stop never kicks in here.
    monkeypatch.setattr(bot_module, "AUTO_STOP_GRACE_SECONDS", 60)
    bot_module._active_streams.clear()
    yield
    for active in bot_module._active_streams.values():
        if active.auto_stop is not None:
            active.auto_stop.cancel()
    bot_module._active_streams.clear()


def _streaming_voice_client():
    owner = MagicMock()
    owner.id = OWNER_ID
    owner.bot = False
    voice_client = MagicMock()
    voice_client.guild.id = STREAM_GUILD_ID
    voice_client.guild.name = "Rehearsal Room"
    voice_client.channel.members = [owner]
    voice_client.is_playing.return_value = True
    voice_client.disconnect = AsyncMock()
    source = MagicMock(spec=DeviceAudioSource)
    source.state = "running"
    source.device_name = "Blackstar ID:Core V4"
    source.volume = 1.0
    voice_client.source = source
    return voice_client


def _ctx(guild_id, *, voice_client=None, in_voice=True):
    ctx = AsyncMock()
    ctx.author = MagicMock()
    ctx.author.id = OWNER_ID
    ctx.guild_id = guild_id
    ctx.voice_client = voice_client
    ctx.channel.send = AsyncMock()
    if in_voice:
        ctx.author.voice.channel = AsyncMock()
        ctx.author.voice.channel.name = "General"
        ctx.author.voice.channel.connect = AsyncMock()
    else:
        ctx.author.voice = None
    return ctx


def _start_stream_in_first_guild():
    voice_client = _streaming_voice_client()
    bot_module._register_stream(_ctx(STREAM_GUILD_ID, voice_client=voice_client), voice_client)
    return voice_client


def _reply(ctx):
    return ctx.respond.await_args.args[0]


async def test_stream_is_refused_while_streaming_in_another_server():
    _start_stream_in_first_guild()
    ctx = _ctx(OTHER_GUILD_ID)

    await stream(ctx)

    ctx.author.voice.channel.connect.assert_not_awaited()
    assert "Already streaming in **Rehearsal Room**" in _reply(ctx)
    assert ctx.respond.await_args.kwargs.get("ephemeral") is True


async def test_stream_is_refused_while_another_start_is_in_flight(monkeypatch):
    """Two /stream calls racing from two servers must not both open the amp."""
    monkeypatch.setattr(bot_module, "_stream_starting", True)
    ctx = _ctx(OTHER_GUILD_ID)

    await stream(ctx)

    ctx.author.voice.channel.connect.assert_not_awaited()
    assert "Already streaming" in _reply(ctx)


async def test_start_flag_is_released_even_when_starting_fails():
    ctx = _ctx(OTHER_GUILD_ID)
    ctx.author.voice.channel.connect = AsyncMock(side_effect=RuntimeError("handshake failed"))

    with (
        patch.object(bot_module, "refresh_devices"),
        patch.object(bot_module, "find_device_by_name", return_value=MagicMock(name="dev")),
        patch.object(bot_module, "CONNECT_RETRY_DELAY_SECONDS", 0),
    ):
        await stream(ctx)

    assert bot_module._stream_starting is False
    assert bot_module._active_streams == {}


async def test_stop_from_another_server_stops_the_stream():
    voice_client = _start_stream_in_first_guild()
    ctx = _ctx(OTHER_GUILD_ID)

    await stop(ctx)

    voice_client.disconnect.assert_awaited_once()
    voice_client.source.cleanup.assert_called_once()
    assert bot_module._active_streams == {}
    assert _reply(ctx) == "Stopped streaming."


async def test_status_from_another_server_reports_the_active_stream():
    _start_stream_in_first_guild()
    ctx = _ctx(OTHER_GUILD_ID)

    await status(ctx)

    assert "Streaming from **Blackstar ID:Core V4**" in _reply(ctx)


async def test_volume_from_another_server_adjusts_the_active_stream():
    voice_client = _start_stream_in_first_guild()
    ctx = _ctx(OTHER_GUILD_ID)

    await volume(ctx, 0.5)

    voice_client.source.set_volume.assert_called_once_with(0.5)


async def test_stop_with_no_stream_anywhere_says_so():
    ctx = _ctx(OTHER_GUILD_ID)

    await stop(ctx)

    assert _reply(ctx) == "Not currently in a voice channel."
