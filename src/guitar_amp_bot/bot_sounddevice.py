"""Discord bot that streams the amp, captured via sounddevice (default) or FFmpeg."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

import discord
from pydantic import ValidationError

from guitar_amp_bot.audio_source import DeviceAudioSource
from guitar_amp_bot.authz import require_owner
from guitar_amp_bot.config import Settings
from guitar_amp_bot.device_finder import (
    DEFAULT_INPUT_CHANNELS,
    AmbiguousDeviceError,
    AudioDevice,
    find_device_by_name,
    format_input_channels,
    list_input_devices,
    refresh_devices,
    refresh_devices_if_idle,
)
from guitar_amp_bot.logging_setup import configure_logging
from guitar_amp_bot.startup import announce_startup

if TYPE_CHECKING:
    from collections.abc import Coroutine

logger = logging.getLogger(__name__)
_settings: Settings | None = None
_volume_override: float | None = None

CONNECT_ATTEMPTS = 2
CONNECT_RETRY_DELAY_SECONDS = 1.0
MAX_DEVICE_LIST_ITEMS = 10
# How long a stream may run unattended (owner gone, or nobody listening)
# before it is stopped. Long enough to survive a quick reconnect.
AUTO_STOP_GRACE_SECONDS = 30.0


class VoiceChannel(Protocol):
    """Minimal voice channel interface used by command handlers."""

    name: str

    async def connect(self) -> VoiceClient:
        """Connect the bot to this voice channel."""
        ...


class VoiceClient(Protocol):
    """Minimal Discord voice client interface used by command handlers."""

    source: object

    def is_playing(self) -> bool:
        """Return whether audio playback is active."""
        ...

    def stop(self) -> None:
        """Stop audio playback."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from the voice channel."""
        ...

    def play(
        self,
        source: object,
        *,
        signal_type: str = "auto",
        after: object | None = None,
        wait_finish: bool = False,
    ) -> None:
        """Start audio playback.

        Mirrors ``discord.voice.VoiceClient.play``. Keep this in step with
        py-cord: a parameter here that the library does not have makes mypy
        validate calls against an API that does not exist. ``signal_type``
        requires py-cord >= 2.8.
        """
        ...


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings


def _set_volume_override(volume: float) -> None:
    global _volume_override
    _volume_override = volume


def _effective_volume(settings: Settings) -> float:
    if _volume_override is not None:
        return _volume_override
    return settings.volume


def _describe_input_channels(channels: tuple[int, ...]) -> str:
    """Say which device inputs are streamed, e.g. "inputs 1+2 (stereo)"."""
    if len(channels) == 1:
        return f"input {channels[0]} (mono)"
    return f"inputs {'+'.join(str(channel) for channel in channels)} (stereo)"


def _ffmpeg_input_args(device_name: str) -> tuple[str, str]:
    """Return (input_source, before_options) for the current platform."""
    if sys.platform == "darwin":
        return (f":{device_name}", "-f avfoundation -ar 48000 -ac 2")
    if sys.platform == "win32":
        return (f"audio={device_name}", "-f dshow -ar 48000 -ac 2")
    return (f"hw:{device_name}", "-f alsa -ar 48000 -ac 2")


def _list_devices_fresh() -> list[AudioDevice]:
    """List input devices, re-enumerated so hot-plug changes show up.

    Reinitializing PortAudio under an open stream is undefined behaviour, so a
    listing taken while streaming shows PortAudio's cached list instead.
    """
    refresh_devices_if_idle()
    return list_input_devices()


def _format_device_list(devices: list[AudioDevice]) -> str:
    if not devices:
        return "No audio input devices were detected."

    lines = ["Detected audio input devices:"]
    for device in devices[:MAX_DEVICE_LIST_ITEMS]:
        hostapi = f"{device.hostapi}, " if device.hostapi else ""
        lines.append(
            f"- `{device.name}` ({hostapi}{device.max_input_channels} input channels, "
            f"{device.default_samplerate:g} Hz default)"
        )
    if len(devices) > MAX_DEVICE_LIST_ITEMS:
        lines.append(f"...and {len(devices) - MAX_DEVICE_LIST_ITEMS} more.")
    return "\n".join(lines)


def _active_sounddevice_source(voice_client: object) -> DeviceAudioSource | None:
    source = getattr(voice_client, "source", None)
    if isinstance(source, DeviceAudioSource):
        return source
    return None


async def _connect_with_retry(channel: VoiceChannel) -> VoiceClient:
    last_error: Exception | None = None
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            logger.info(
                "voice_connect_attempt",
                extra={"channel": getattr(channel, "name", "?"), "attempt": attempt},
            )
            return await channel.connect()
        except Exception as exc:
            last_error = exc
            logger.warning(
                "voice_connect_failed",
                extra={"channel": getattr(channel, "name", "?"), "attempt": attempt},
                exc_info=True,
            )
            if attempt < CONNECT_ATTEMPTS:
                await asyncio.sleep(CONNECT_RETRY_DELAY_SECONDS)
    if last_error is not None:
        raise last_error
    msg = "voice connection failed without an exception"
    raise RuntimeError(msg)


async def _disconnect_quietly(voice_client: VoiceClient) -> None:
    with contextlib.suppress(Exception):
        await voice_client.disconnect()


async def _send_channel_message(ctx: discord.ApplicationContext, message: str) -> None:
    channel = getattr(ctx, "channel", None)
    send = getattr(channel, "send", None)
    if send is not None:
        await send(message)


def _schedule_on_loop(coro: Coroutine[Any, Any, None]) -> None:
    """Run *coro* on the bot's event loop from a non-loop thread.

    Playback callbacks and the device watchdog both run on their own threads,
    where ``loop.create_task`` is not thread-safe.
    """
    loop = getattr(bot, "loop", None)
    if loop is None:
        coro.close()
        return
    try:
        asyncio.run_coroutine_threadsafe(coro, loop)
    except Exception:
        coro.close()
        logger.warning("loop_schedule_failed", exc_info=True)


@dataclass
class _ActiveStream:
    """A running stream and who it is for, tracked per guild."""

    owner_id: int
    ctx: discord.ApplicationContext
    voice_client: VoiceClient
    auto_stop: asyncio.Task[None] | None = None


_active_streams: dict[int, _ActiveStream] = {}
# One amp, one stream: set while a /stream is connecting, before the stream is
# registered, so a second /stream from another server cannot race past the check.
_stream_starting = False


def _current_stream() -> _ActiveStream | None:
    """Return the instance's single active stream, wherever it is."""
    return next(iter(_active_streams.values()), None)


def _voice_client_for(ctx: discord.ApplicationContext) -> VoiceClient | None:
    """Return the stream's voice client, from this server or any other.

    Commands are global for a self-hosted instance, so the owner may run
    /stop or /status from a different server than the one being streamed to.
    """
    if ctx.voice_client is not None:
        # py-cord's VoiceClient satisfies the local protocol at runtime; its
        # overloaded play() signature is what keeps mypy from seeing that.
        return cast("VoiceClient", ctx.voice_client)
    active = _current_stream()
    return None if active is None else active.voice_client


def _stream_location(active: _ActiveStream | None) -> str:
    guild_name = getattr(
        getattr(getattr(active, "voice_client", None), "guild", None), "name", None
    )
    return f" in **{guild_name}**" if isinstance(guild_name, str) else ""


def _guild_id_of(voice_client: object, ctx: discord.ApplicationContext) -> int | None:
    guild_id = getattr(getattr(voice_client, "guild", None), "id", None)
    if not isinstance(guild_id, int):
        guild_id = getattr(ctx, "guild_id", None)
    return guild_id if isinstance(guild_id, int) else None


def _register_stream(ctx: discord.ApplicationContext, voice_client: VoiceClient) -> None:
    """Track a started stream so voice-state changes can stop it."""
    guild_id = _guild_id_of(voice_client, ctx)
    owner_id = getattr(getattr(ctx, "author", None), "id", None)
    if guild_id is None or not isinstance(owner_id, int):
        return
    _active_streams[guild_id] = _ActiveStream(owner_id, ctx, voice_client)
    # The owner may already have left during the voice handshake.
    _evaluate_listeners(guild_id)


def _forget_stream(voice_client: object) -> None:
    """Stop tracking the stream on *voice_client* and cancel any pending auto-stop."""
    for guild_id, active in list(_active_streams.items()):
        if active.voice_client is voice_client:
            del _active_streams[guild_id]
            if active.auto_stop is not None:
                active.auto_stop.cancel()


def _unattended_reason(active: _ActiveStream) -> str | None:
    """Return why nobody should be hearing this stream, or None if someone is."""
    channel = getattr(active.voice_client, "channel", None)
    members = getattr(channel, "members", None) or []
    humans = [member for member in members if not getattr(member, "bot", False)]
    if not humans:
        return "channel_empty"
    if all(getattr(member, "id", None) != active.owner_id for member in humans):
        return "owner_left"
    return None


def _evaluate_listeners(guild_id: int) -> None:
    """Start or cancel the auto-stop timer for *guild_id*'s stream."""
    active = _active_streams.get(guild_id)
    if active is None:
        return
    reason = _unattended_reason(active)
    if reason is None:
        if active.auto_stop is not None:
            active.auto_stop.cancel()
            active.auto_stop = None
            logger.info("auto_stop_cancelled guild=%s", guild_id)
        return
    if active.auto_stop is None:
        active.auto_stop = asyncio.create_task(_auto_stop_after_grace(guild_id))
        logger.info(
            "auto_stop_scheduled guild=%s reason=%s grace=%gs",
            guild_id,
            reason,
            AUTO_STOP_GRACE_SECONDS,
        )


async def _auto_stop_after_grace(guild_id: int) -> None:
    """Stop the stream if it is still unattended once the grace period ends."""
    await asyncio.sleep(AUTO_STOP_GRACE_SECONDS)
    active = _active_streams.get(guild_id)
    if active is None:
        return
    # This task is finishing; it must not be cancelled by the teardown below.
    active.auto_stop = None
    reason = _unattended_reason(active)
    if reason is None:
        return
    await _teardown(active.voice_client)
    logger.info("stream_stopped reason=auto_stop guild=%s cause=%s", guild_id, reason)
    # No device name: this notice is public.
    await _send_channel_message(active.ctx, "Stopped streaming because nobody was listening.")


async def _teardown(voice_client: VoiceClient) -> None:
    """Stop playback, release the capture device and leave the voice channel."""
    _forget_stream(voice_client)
    source = _active_sounddevice_source(voice_client)
    with contextlib.suppress(Exception):
        if voice_client.is_playing():
            voice_client.stop()
    if source is not None:
        # Can wait seconds for the capture watchdog to exit; keep the loop free.
        await asyncio.to_thread(source.cleanup)
    await _disconnect_quietly(voice_client)


async def _handle_device_unavailable(
    ctx: discord.ApplicationContext, voice_client: VoiceClient
) -> None:
    """Tear down the stream after the capture device stayed gone."""
    await _teardown(voice_client)
    # Deliberately no device name: this notice is public, and device names are
    # treated as private (that is why /devices replies ephemerally).
    await _send_channel_message(
        ctx, "Audio device was lost, so streaming stopped. See the bot log for details."
    )


def _after_playback(
    ctx: discord.ApplicationContext,
    source: DeviceAudioSource | None,
    error: Exception | None,
) -> None:
    if source is not None:
        source.cleanup()
    if error is None:
        return
    logger.error("playback_error", extra={"error": str(error)}, exc_info=error)
    _schedule_on_loop(_send_channel_message(ctx, "Playback stopped unexpectedly; see the bot log."))


async def _start_sounddevice_stream(
    ctx: discord.ApplicationContext,
    channel: VoiceChannel,
    device_name: str,
    volume: float,
    input_channels: tuple[int, ...] = DEFAULT_INPUT_CHANNELS,
) -> None:
    # PortAudio caches its device list, so an already-unplugged amp can still
    # be listed with an index that now belongs to another input.
    # Both reinitialize or query PortAudio, which blocks; run them off the loop.
    await asyncio.to_thread(refresh_devices)
    try:
        device = await asyncio.to_thread(find_device_by_name, device_name, input_channels)
    except AmbiguousDeviceError as exc:
        logger.info("audio_device_ambiguous", extra={"candidates": exc.candidates})
        names = "\n".join(f"- `{name}`" for name in exc.candidates)
        await ctx.respond(
            f"Audio device query '{device_name}' matches several inputs:\n{names}\n"
            "Set `AUDIO_DEVICE` to one of these exact names.",
            ephemeral=True,
        )
        return
    if device is None:
        logger.info("audio_device_not_found", extra={"device_query": device_name})
        await ctx.respond(
            f"Audio device matching '{device_name}' was not found. "
            "Use `/devices` to see detected inputs.",
            ephemeral=True,
        )
        return

    voice_client: VoiceClient | None = None
    source: DeviceAudioSource | None = None
    try:
        voice_client = await _connect_with_retry(channel)
        connected = voice_client
        source = DeviceAudioSource(
            device,
            volume=volume,
            device_query=device_name,
            on_unavailable=lambda: _schedule_on_loop(_handle_device_unavailable(ctx, connected)),
            input_channels=input_channels,
        )
        await asyncio.to_thread(source.start)
        voice_client.play(
            source,
            signal_type="music",
            after=lambda error: _after_playback(ctx, source, error),
        )
    except Exception as exc:
        if source is not None:
            await asyncio.to_thread(source.cleanup)
        if voice_client is not None:
            await _disconnect_quietly(voice_client)
        logger.warning(
            "sounddevice_stream_start_failed",
            extra={"device": device.name, "volume": volume},
            exc_info=True,
        )
        await ctx.respond(f"Could not start streaming from '{device.name}': {exc}", ephemeral=True)
        return

    _register_stream(ctx, voice_client)
    logger.info(
        "sounddevice_stream_started",
        extra={
            "device": device.name,
            "channel": getattr(channel, "name", "?"),
            "volume": volume,
            "input_channels": format_input_channels(input_channels),
        },
    )
    await ctx.respond(f"Streaming audio from **{device.name}** in {channel.name}.")


async def _start_ffmpeg_stream(
    ctx: discord.ApplicationContext,
    channel: VoiceChannel,
    device_name: str,
    input_channels: tuple[int, ...] = DEFAULT_INPUT_CHANNELS,
) -> None:
    if input_channels != DEFAULT_INPUT_CHANNELS:
        logger.warning(
            "input_channels_ignored: INPUT_CHANNELS applies to the sounddevice backend "
            "only; FFmpeg captures the device's own stereo",
            extra={"input_channels": format_input_channels(input_channels)},
        )
    voice_client: VoiceClient | None = None
    try:
        voice_client = await _connect_with_retry(channel)
        input_source, before_options = _ffmpeg_input_args(device_name)
        source = discord.FFmpegPCMAudio(input_source, before_options=before_options)
        voice_client.play(
            source,
            signal_type="music",
            after=lambda error: _after_playback(ctx, None, error),
        )
    except Exception as exc:
        if voice_client is not None:
            await _disconnect_quietly(voice_client)
        logger.warning(
            "ffmpeg_stream_start_failed",
            extra={"device": device_name, "platform": sys.platform},
            exc_info=True,
        )
        await ctx.respond(
            f"Could not start FFmpeg streaming from '{device_name}': {exc}", ephemeral=True
        )
        return

    _register_stream(ctx, voice_client)
    logger.info(
        "ffmpeg_stream_started",
        extra={
            "device": device_name,
            "channel": getattr(channel, "name", "?"),
            "platform": sys.platform,
        },
    )
    await ctx.respond(f"Streaming audio from **{device_name}** via FFmpeg in {channel.name}.")


def _resolve_guild_ids() -> list[int] | None:
    """Return the guild scope for slash-command registration, or None for global.

    Evaluated at import time because py-cord's decorators need ``guild_ids``
    then, so an unreadable configuration must not raise here — ``main()``
    surfaces the real error and warns about the missing scope.
    """
    try:
        guild_id = _get_settings().guild_id
    except ValidationError:
        return None
    return None if guild_id is None else [guild_id]


GUILD_IDS = _resolve_guild_ids()

bot: Any = discord.Bot(intents=discord.Intents.default())


@bot.event
async def on_ready() -> None:
    """Log when the bot is connected and ready."""
    logger.info("Logged in as %s (id=%s)", bot.user, bot.user.id if bot.user else "?")
    await announce_startup(bot, _get_settings())


@bot.event
async def on_voice_state_update(
    member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
) -> None:
    """Stop streaming once nobody it is meant for is listening."""
    guild_id = getattr(getattr(member, "guild", None), "id", None)
    active = _active_streams.get(guild_id) if isinstance(guild_id, int) else None
    if active is None or guild_id is None:
        return

    bot_user_id = getattr(getattr(bot, "user", None), "id", None)
    if member.id == bot_user_id and after.channel is None:
        # Kicked, channel deleted, or disconnected elsewhere: the voice client
        # is already gone, so only the capture side needs releasing.
        _forget_stream(active.voice_client)
        source = _active_sounddevice_source(active.voice_client)
        if source is not None:
            await asyncio.to_thread(source.cleanup)
        logger.info("stream_stopped reason=bot_disconnected guild=%s", guild_id)
        return

    _evaluate_listeners(guild_id)


@bot.slash_command(
    description="Stream your amp into your voice channel",
    guild_ids=GUILD_IDS,
)
async def stream(ctx: discord.ApplicationContext) -> None:
    """Join the owner's voice channel and start streaming the configured audio device."""
    global _stream_starting
    if not await require_owner(ctx, _get_settings().owner_id):
        return

    # The voice handshake takes longer than Discord's 3s interaction deadline,
    # so acknowledge first; every later ctx.respond becomes a followup and keeps
    # its own ephemeral flag.
    await ctx.defer(ephemeral=True)

    voice_state = getattr(ctx.author, "voice", None)
    if voice_state is None or voice_state.channel is None:
        await ctx.respond(
            "You must be in a voice channel before starting a stream.", ephemeral=True
        )
        return

    active = _current_stream()
    if ctx.voice_client is not None or active is not None or _stream_starting:
        # Ephemeral, so naming the server only tells the owner where it is.
        await ctx.respond(
            f"Already streaming{_stream_location(active)}. Use `/stop` before starting again.",
            ephemeral=True,
        )
        return

    s = _get_settings()
    selected_backend = s.audio_backend
    selected_device = s.audio_device
    channel = voice_state.channel

    if s.debug_config:
        logger.info(
            "stream_config",
            extra={
                "backend": selected_backend,
                "device": selected_device,
                "input_channels": format_input_channels(s.input_channels),
                "volume": _effective_volume(s),
            },
        )

    _stream_starting = True
    try:
        if selected_backend == "sounddevice":
            await _start_sounddevice_stream(
                ctx, channel, selected_device, _effective_volume(s), s.input_channels
            )
        else:
            await _start_ffmpeg_stream(ctx, channel, selected_device, s.input_channels)
    finally:
        _stream_starting = False


@bot.slash_command(
    description="Stop streaming and leave the voice channel",
    guild_ids=GUILD_IDS,
)
async def stop(ctx: discord.ApplicationContext) -> None:
    """Stop playback and disconnect from the voice channel."""
    if not await require_owner(ctx, _get_settings().owner_id):
        return

    await ctx.defer(ephemeral=True)

    voice_client = _voice_client_for(ctx)
    if voice_client is None:
        await ctx.respond("Not currently in a voice channel.", ephemeral=True)
        return
    await _teardown(voice_client)
    logger.info("stream_stopped")
    await ctx.respond("Stopped streaming.")


@bot.slash_command(
    description="Show the current streaming status",
    guild_ids=GUILD_IDS,
)
async def status(ctx: discord.ApplicationContext) -> None:
    """Report whether the bot is currently streaming."""
    if not await require_owner(ctx, _get_settings().owner_id):
        return

    vc = _voice_client_for(ctx)
    if vc is None:
        await ctx.respond(
            "Not streaming. Use `/stream` from a voice channel to start.", ephemeral=True
        )
        return

    source = _active_sounddevice_source(vc)
    if source is not None:
        if source.state == "reacquiring":
            await ctx.respond(
                "Audio device was lost — muted and re-acquiring it. "
                "Audio resumes automatically if it comes back.",
                ephemeral=True,
            )
            return
        await ctx.respond(
            f"Streaming from **{source.device_name}**, "
            f"{_describe_input_channels(source.input_channels)}, "
            f"with volume `{source.volume:g}`.",
            ephemeral=True,
        )
        return

    await ctx.respond("Streaming via FFmpeg or another Discord audio source.", ephemeral=True)


@bot.slash_command(
    description="List detected audio input devices",
    guild_ids=GUILD_IDS,
)
async def devices(ctx: discord.ApplicationContext) -> None:
    """List available local audio input devices."""
    if not await require_owner(ctx, _get_settings().owner_id):
        return

    detected_devices = await asyncio.to_thread(_list_devices_fresh)
    logger.info("audio_devices_listed", extra={"count": len(detected_devices)})
    await ctx.respond(_format_device_list(detected_devices), ephemeral=True)


@bot.slash_command(
    description="Show or change the current stream volume",
    guild_ids=GUILD_IDS,
)
async def volume(ctx: discord.ApplicationContext, level: float | None = None) -> None:
    """Show or change the sounddevice playback volume."""
    s = _get_settings()
    if not await require_owner(ctx, s.owner_id):
        return

    if level is None:
        await ctx.respond(
            f"Current configured volume is `{_effective_volume(s):g}`.", ephemeral=True
        )
        return

    if level < 0.0 or level > 5.0:
        await ctx.respond("Volume must be between `0.0` and `5.0`.", ephemeral=True)
        return

    _set_volume_override(level)
    voice_client = _voice_client_for(ctx)
    source = _active_sounddevice_source(voice_client) if voice_client is not None else None
    if source is not None:
        source.set_volume(level)
        await ctx.respond(f"Updated active stream volume to `{level:g}`.", ephemeral=True)
        return

    await ctx.respond(f"Volume set to `{level:g}` for the next sounddevice stream.", ephemeral=True)


def main() -> None:
    """Entry point for running the bot."""
    settings = _get_settings()
    configure_logging(settings)
    if settings.guild_id is None:
        logger.info(
            "guild_scope_global: commands are available in every server this bot "
            "joins; set GUILD_ID to register them in a single server only"
        )
    elif GUILD_IDS is None:
        logger.warning(
            "guild_scope_unavailable: GUILD_ID was not readable when commands were "
            "registered, so they are registered globally; run from the directory "
            "holding your .env file"
        )
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
