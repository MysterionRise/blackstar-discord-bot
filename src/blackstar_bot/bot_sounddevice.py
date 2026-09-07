"""Alternative Discord bot — Approach A (sounddevice-based audio streaming)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from typing import Any, Protocol

import discord
from pydantic import ValidationError

from blackstar_bot.audio_source import BlackstarAudioSource
from blackstar_bot.authz import require_owner
from blackstar_bot.config import Settings
from blackstar_bot.device_finder import AudioDevice, find_device_by_name, list_input_devices
from blackstar_bot.logging_setup import configure_logging

logger = logging.getLogger(__name__)
_settings: Settings | None = None
_volume_override: float | None = None

CONNECT_ATTEMPTS = 2
CONNECT_RETRY_DELAY_SECONDS = 1.0
MAX_DEVICE_LIST_ITEMS = 10


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
        signal_type: str,
        after: object | None = None,
    ) -> None:
        """Start audio playback."""
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


def _ffmpeg_input_args(device_name: str) -> tuple[str, str]:
    """Return (input_source, before_options) for the current platform."""
    if sys.platform == "darwin":
        return (f":{device_name}", "-f avfoundation -ar 48000 -ac 2")
    if sys.platform == "win32":
        return (f"audio={device_name}", "-f dshow -ar 48000 -ac 2")
    return (f"hw:{device_name}", "-f alsa -ar 48000 -ac 2")


def _format_device_list(devices: list[AudioDevice]) -> str:
    if not devices:
        return "No audio input devices were detected."

    lines = ["Detected audio input devices:"]
    for device in devices[:MAX_DEVICE_LIST_ITEMS]:
        lines.append(
            f"- `{device.name}` ({device.max_input_channels} input channels, "
            f"{device.default_samplerate:g} Hz)"
        )
    if len(devices) > MAX_DEVICE_LIST_ITEMS:
        lines.append(f"...and {len(devices) - MAX_DEVICE_LIST_ITEMS} more.")
    return "\n".join(lines)


def _active_sounddevice_source(voice_client: object) -> BlackstarAudioSource | None:
    source = getattr(voice_client, "source", None)
    if isinstance(source, BlackstarAudioSource):
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


def _after_playback(
    ctx: discord.ApplicationContext,
    source: BlackstarAudioSource | None,
    error: Exception | None,
) -> None:
    if source is not None:
        source.cleanup()
    if error is None:
        return
    logger.error("playback_error", extra={"error": str(error)}, exc_info=error)
    with contextlib.suppress(Exception):
        bot.loop.create_task(
            _send_channel_message(ctx, "Playback stopped unexpectedly; see the bot log.")
        )


async def _start_sounddevice_stream(
    ctx: discord.ApplicationContext,
    channel: VoiceChannel,
    device_name: str,
    volume: float,
) -> None:
    device = find_device_by_name(device_name)
    if device is None:
        logger.info("audio_device_not_found", extra={"device_query": device_name})
        await ctx.respond(
            f"Audio device matching '{device_name}' was not found. "
            "Use `/devices` to see detected inputs.",
            ephemeral=True,
        )
        return

    voice_client: VoiceClient | None = None
    source: BlackstarAudioSource | None = None
    try:
        voice_client = await _connect_with_retry(channel)
        source = BlackstarAudioSource(device, volume=volume)
        source.start()
        voice_client.play(
            source,
            signal_type="music",
            after=lambda error: _after_playback(ctx, source, error),
        )
    except Exception as exc:
        if source is not None:
            source.cleanup()
        if voice_client is not None:
            await _disconnect_quietly(voice_client)
        logger.warning(
            "sounddevice_stream_start_failed",
            extra={"device": device.name, "volume": volume},
            exc_info=True,
        )
        await ctx.respond(f"Could not start streaming from '{device.name}': {exc}", ephemeral=True)
        return

    logger.info(
        "sounddevice_stream_started",
        extra={"device": device.name, "channel": getattr(channel, "name", "?"), "volume": volume},
    )
    await ctx.respond(f"Streaming audio from **{device.name}** in {channel.name}.")


async def _start_ffmpeg_stream(
    ctx: discord.ApplicationContext,
    channel: VoiceChannel,
    device_name: str,
) -> None:
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


@bot.slash_command(
    description="Stream Blackstar amp audio into your voice channel",
    guild_ids=GUILD_IDS,
)
async def stream(ctx: discord.ApplicationContext) -> None:
    """Join the owner's voice channel and start streaming the configured audio device."""
    if not await require_owner(ctx, _get_settings().owner_id):
        return

    voice_state = getattr(ctx.author, "voice", None)
    if voice_state is None or voice_state.channel is None:
        await ctx.respond(
            "You must be in a voice channel before starting a stream.", ephemeral=True
        )
        return

    if ctx.voice_client is not None:
        await ctx.respond(
            "Already streaming in a voice channel. Use `/stop` before starting again.",
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
                "volume": _effective_volume(s),
            },
        )

    if selected_backend == "sounddevice":
        await _start_sounddevice_stream(ctx, channel, selected_device, _effective_volume(s))
        return

    await _start_ffmpeg_stream(ctx, channel, selected_device)


@bot.slash_command(
    description="Stop streaming and leave the voice channel",
    guild_ids=GUILD_IDS,
)
async def stop(ctx: discord.ApplicationContext) -> None:
    """Stop playback and disconnect from the voice channel."""
    if not await require_owner(ctx, _get_settings().owner_id):
        return

    if ctx.voice_client is None:
        await ctx.respond("Not currently in a voice channel.", ephemeral=True)
        return
    vc = ctx.voice_client
    if vc.is_playing():
        vc.stop()
    source = _active_sounddevice_source(vc)
    if source is not None:
        source.cleanup()
    await vc.disconnect()
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

    if ctx.voice_client is None:
        await ctx.respond(
            "Not streaming. Use `/stream` from a voice channel to start.", ephemeral=True
        )
        return

    vc = ctx.voice_client
    source = _active_sounddevice_source(vc)
    if source is not None:
        await ctx.respond(
            f"Streaming from **{source.device_name}** with volume `{source.volume:g}`.",
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

    detected_devices = list_input_devices()
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
    source = _active_sounddevice_source(ctx.voice_client) if ctx.voice_client is not None else None
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
        logger.warning(
            "guild_scope_missing: commands are registered globally; "
            "set GUILD_ID to register them in a single server only"
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
