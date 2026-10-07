"""Blocking PortAudio work must run off the event loop that serves Discord."""

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import guitar_amp_bot.bot_sounddevice as bot_module
from guitar_amp_bot.audio_source import DeviceAudioSource
from guitar_amp_bot.bot_sounddevice import devices, stop, stream
from guitar_amp_bot.device_finder import AudioDevice

OWNER_ID = 424242424242424242
GUILD_ID = 123456789012345678


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
    monkeypatch.setattr(bot_module, "AUTO_STOP_GRACE_SECONDS", 60)
    bot_module._active_streams.clear()
    yield
    for active in bot_module._active_streams.values():
        if active.auto_stop is not None:
            active.auto_stop.cancel()
    bot_module._active_streams.clear()


def _recording(threads, name, result=None):
    def _call(*_args, **_kwargs):
        threads[name] = threading.get_ident()
        return result

    return _call


def _ctx(voice_client=None):
    ctx = AsyncMock()
    ctx.author = MagicMock()
    ctx.author.id = OWNER_ID
    ctx.guild_id = GUILD_ID
    ctx.voice_client = voice_client
    ctx.author.voice.channel = AsyncMock()
    ctx.author.voice.channel.name = "General"
    return ctx


async def test_devices_command_lists_inputs_off_the_event_loop():
    threads = {}
    with (
        patch.object(bot_module, "refresh_devices_if_idle", _recording(threads, "refresh")),
        patch.object(bot_module, "list_input_devices", _recording(threads, "list", [])),
    ):
        await devices(_ctx())

    loop_thread = threading.get_ident()
    assert {"refresh", "list"} <= threads.keys()
    assert all(thread != loop_thread for thread in threads.values())


async def test_stream_start_runs_portaudio_work_off_the_event_loop():
    threads = {}
    device = AudioDevice(
        index=5, name="Blackstar ID:Core V4", max_input_channels=2, default_samplerate=48000.0
    )
    source = MagicMock()
    source.start.side_effect = _recording(threads, "start")
    voice_client = MagicMock()
    voice_client.guild.id = GUILD_ID
    ctx = _ctx()
    ctx.author.voice.channel.connect = AsyncMock(return_value=voice_client)

    with (
        patch.object(bot_module, "refresh_devices", _recording(threads, "refresh")),
        patch.object(bot_module, "find_device_by_name", _recording(threads, "find", device)),
        patch.object(bot_module, "DeviceAudioSource", return_value=source),
    ):
        await stream(ctx)

    loop_thread = threading.get_ident()
    assert {"refresh", "find", "start"} <= threads.keys()
    assert all(thread != loop_thread for thread in threads.values())


async def test_stop_releases_the_capture_device_off_the_event_loop():
    """cleanup() can wait seconds for the watchdog thread to exit."""
    threads = {}
    voice_client = MagicMock()
    voice_client.is_playing.return_value = True
    voice_client.disconnect = AsyncMock()
    voice_client.source = MagicMock(spec=DeviceAudioSource)
    voice_client.source.cleanup.side_effect = _recording(threads, "cleanup")

    await stop(_ctx(voice_client))

    assert threads["cleanup"] != threading.get_ident()
    voice_client.disconnect.assert_awaited_once()
