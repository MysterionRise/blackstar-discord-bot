"""Integration tests for stopping a stream once nobody it is meant for is listening."""

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import discord.voice
import pytest

import guitar_amp_bot.bot_sounddevice as bot_module
from guitar_amp_bot.audio_source import DeviceAudioSource
from guitar_amp_bot.bot_sounddevice import on_voice_state_update, stop, stream
from guitar_amp_bot.device_finder import AudioDevice

OWNER_ID = 424242424242424242
FRIEND_ID = 111111111111111111
BOT_ID = 555555555555555555
GUILD_ID = 123456789012345678


@pytest.fixture(autouse=True)
def runtime_state(monkeypatch):
    """Isolate module state and make the grace period immediate by default."""
    settings = MagicMock()
    settings.owner_id = OWNER_ID
    monkeypatch.setattr(bot_module, "_settings", settings)
    monkeypatch.setattr(bot_module, "AUTO_STOP_GRACE_SECONDS", 0)
    monkeypatch.setattr(bot_module, "bot", MagicMock(user=MagicMock(id=BOT_ID)))
    bot_module._active_streams.clear()
    yield
    for active in bot_module._active_streams.values():
        if active.auto_stop is not None:
            active.auto_stop.cancel()
    bot_module._active_streams.clear()


def _member(member_id, *, is_bot=False):
    member = MagicMock()
    member.id = member_id
    member.bot = is_bot
    member.guild.id = GUILD_ID
    return member


def _voice_client(*members):
    voice_client = MagicMock()
    voice_client.guild.id = GUILD_ID
    voice_client.channel.members = list(members)
    voice_client.is_playing.return_value = True
    voice_client.disconnect = AsyncMock()
    voice_client.source = MagicMock(spec=DeviceAudioSource)
    return voice_client


def _ctx(voice_client=None):
    ctx = AsyncMock()
    ctx.author = MagicMock()
    ctx.author.id = OWNER_ID
    ctx.guild_id = GUILD_ID
    ctx.channel.send = AsyncMock()
    ctx.voice_client = voice_client
    return ctx


def _voice_state(channel):
    state = MagicMock()
    state.channel = channel
    return state


async def _leave(voice_client, member):
    """Remove *member* from the bot's channel and deliver the voice-state event."""
    voice_client.channel.members.remove(member)
    await on_voice_state_update(member, _voice_state(voice_client.channel), _voice_state(None))


async def _join(voice_client, member):
    voice_client.channel.members.append(member)
    await on_voice_state_update(member, _voice_state(None), _voice_state(voice_client.channel))


def _pending_auto_stop():
    task = bot_module._active_streams[GUILD_ID].auto_stop
    assert task is not None, "expected an auto-stop to be scheduled"
    return task


async def test_owner_leaving_stops_the_stream():
    owner = _member(OWNER_ID)
    voice_client = _voice_client(owner, _member(BOT_ID, is_bot=True), _member(FRIEND_ID))
    ctx = _ctx()
    bot_module._register_stream(ctx, voice_client)

    await _leave(voice_client, owner)
    await _pending_auto_stop()

    voice_client.stop.assert_called_once()
    voice_client.source.cleanup.assert_called_once()
    voice_client.disconnect.assert_awaited_once()
    assert GUILD_ID not in bot_module._active_streams
    ctx.channel.send.assert_awaited_once_with("Stopped streaming because nobody was listening.")


async def test_empty_channel_stops_the_stream_even_if_the_owner_never_spoke():
    """Bots do not count as listeners: once the last human leaves, the stream ends."""
    friend = _member(FRIEND_ID)
    voice_client = _voice_client(_member(OWNER_ID), friend, _member(BOT_ID, is_bot=True))
    bot_module._register_stream(_ctx(), voice_client)
    voice_client.channel.members.remove(voice_client.channel.members[0])

    await _leave(voice_client, friend)
    await _pending_auto_stop()

    voice_client.disconnect.assert_awaited_once()


async def test_owner_rejoining_within_the_grace_period_keeps_streaming(monkeypatch):
    monkeypatch.setattr(bot_module, "AUTO_STOP_GRACE_SECONDS", 60)
    owner = _member(OWNER_ID)
    voice_client = _voice_client(owner)
    bot_module._register_stream(_ctx(), voice_client)

    await _leave(voice_client, owner)
    pending = _pending_auto_stop()
    await _join(voice_client, owner)
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert pending.cancelled()
    voice_client.disconnect.assert_not_awaited()
    assert bot_module._active_streams[GUILD_ID].auto_stop is None


async def test_a_listener_leaving_while_the_owner_stays_changes_nothing():
    friend = _member(FRIEND_ID)
    voice_client = _voice_client(_member(OWNER_ID), friend)
    bot_module._register_stream(_ctx(), voice_client)

    await _leave(voice_client, friend)

    assert bot_module._active_streams[GUILD_ID].auto_stop is None
    voice_client.disconnect.assert_not_awaited()


async def test_owner_absent_at_start_schedules_the_auto_stop_immediately():
    """The owner can leave during the voice handshake; that must not stream forever."""
    voice_client = _voice_client(_member(FRIEND_ID))

    bot_module._register_stream(_ctx(), voice_client)
    await _pending_auto_stop()

    voice_client.disconnect.assert_awaited_once()


async def test_bot_disconnected_externally_releases_the_capture_device():
    voice_client = _voice_client(_member(OWNER_ID))
    bot_module._register_stream(_ctx(), voice_client)
    bot_member = _member(BOT_ID, is_bot=True)

    await on_voice_state_update(bot_member, _voice_state(voice_client.channel), _voice_state(None))

    voice_client.source.cleanup.assert_called_once()
    voice_client.disconnect.assert_not_awaited()
    assert GUILD_ID not in bot_module._active_streams


async def test_stop_command_forgets_the_stream_and_cancels_a_pending_auto_stop(monkeypatch):
    monkeypatch.setattr(bot_module, "AUTO_STOP_GRACE_SECONDS", 60)
    voice_client = _voice_client(_member(FRIEND_ID))
    bot_module._register_stream(_ctx(), voice_client)
    pending = _pending_auto_stop()

    await stop(_ctx(voice_client))
    await asyncio.sleep(0)

    assert pending.cancelled()
    assert GUILD_ID not in bot_module._active_streams
    voice_client.disconnect.assert_awaited_once()


async def test_voice_events_without_an_active_stream_are_ignored():
    voice_client = _voice_client(_member(OWNER_ID))

    await on_voice_state_update(
        _member(OWNER_ID), _voice_state(voice_client.channel), _voice_state(None)
    )

    assert bot_module._active_streams == {}
    voice_client.disconnect.assert_not_awaited()


@pytest.mark.parametrize("backend", ["sounddevice", "ffmpeg"])
async def test_stream_command_registers_the_stream_for_auto_stop(backend):
    """Both backends hand the started stream to the auto-stop tracking."""
    play_signature = inspect.signature(discord.voice.VoiceClient.play)
    voice_client = _voice_client(_member(OWNER_ID))
    voice_client.play = MagicMock(
        side_effect=lambda *a, **k: play_signature.bind(MagicMock(), *a, **k)
    )
    ctx = _ctx()
    ctx.author.voice.channel.connect = AsyncMock(return_value=voice_client)
    bot_module._settings.audio_backend = backend
    bot_module._settings.debug_config = False
    device = AudioDevice(
        index=5, name="Blackstar ID:Core V4", max_input_channels=2, default_samplerate=48000.0
    )

    with (
        patch.object(bot_module, "refresh_devices"),
        patch.object(bot_module, "find_device_by_name", return_value=device),
        patch.object(bot_module, "DeviceAudioSource", return_value=MagicMock()),
        patch.object(bot_module.discord, "FFmpegPCMAudio", return_value=MagicMock()),
    ):
        await stream(ctx)

    active = bot_module._active_streams[GUILD_ID]
    assert active.owner_id == OWNER_ID
    assert active.voice_client is voice_client
    assert active.auto_stop is None
