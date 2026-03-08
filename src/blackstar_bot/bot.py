"""Main Discord bot — Approach B (FFmpeg-based audio streaming)."""

from __future__ import annotations

import logging
import sys
from typing import Any

import discord

from blackstar_bot.config import Settings

logger = logging.getLogger(__name__)
_settings: Settings | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings


def _ffmpeg_input_args(device_name: str) -> tuple[str, str]:
    """Return (input_source, before_options) for the current platform."""
    if sys.platform == "darwin":
        return (f":{device_name}", "-f avfoundation -ar 48000 -ac 2")
    if sys.platform == "win32":
        return (f"audio={device_name}", "-f dshow -ar 48000 -ac 2")
    return (f"hw:{device_name}", "-f alsa -ar 48000 -ac 2")


bot: Any = discord.Bot(intents=discord.Intents.default())


@bot.event
async def on_ready() -> None:
    """Log when the bot is connected and ready."""
    logger.info("Logged in as %s (id=%s)", bot.user, bot.user.id if bot.user else "?")


@bot.slash_command(description="Stream Blackstar amp audio into your voice channel")
async def stream(ctx: discord.ApplicationContext) -> None:
    """Join the user's voice channel and start streaming audio via FFmpeg."""
    if ctx.author.voice is None or ctx.author.voice.channel is None:  # type: ignore[union-attr]
        await ctx.respond("You must be in a voice channel first.")
        return

    if ctx.voice_client is not None:
        await ctx.respond("Already streaming. Use /stop first.")
        return

    channel = ctx.author.voice.channel  # type: ignore[union-attr]
    voice_client = await channel.connect()

    s = _get_settings()
    input_source, before_options = _ffmpeg_input_args(s.audio_device)
    source = discord.FFmpegPCMAudio(input_source, before_options=before_options)
    voice_client.play(source, signal_type="music")
    await ctx.respond(f"Streaming audio from **{s.audio_device}** in {channel.name}.")


@bot.slash_command(description="Stop streaming and leave the voice channel")
async def stop(ctx: discord.ApplicationContext) -> None:
    """Stop playback and disconnect from the voice channel."""
    if ctx.voice_client is None:
        await ctx.respond("Not currently in a voice channel.")
        return
    vc = ctx.voice_client
    if vc.is_playing():
        vc.stop()
    await vc.disconnect()
    await ctx.respond("Stopped streaming.")


def main() -> None:
    """Entry point for running the bot."""
    logging.basicConfig(level=logging.INFO)
    bot.run(_get_settings().discord_token)


if __name__ == "__main__":
    main()
