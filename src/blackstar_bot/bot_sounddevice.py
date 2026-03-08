"""Alternative Discord bot — Approach A (sounddevice-based audio streaming)."""

from __future__ import annotations

import logging
from typing import Any

import discord

from blackstar_bot.audio_source import BlackstarAudioSource
from blackstar_bot.config import Settings
from blackstar_bot.device_finder import find_device_by_name

logger = logging.getLogger(__name__)
_settings: Settings | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings


bot: Any = discord.Bot(intents=discord.Intents.default())


@bot.event
async def on_ready() -> None:
    """Log when the bot is connected and ready."""
    logger.info("Logged in as %s (id=%s)", bot.user, bot.user.id if bot.user else "?")


@bot.slash_command(description="Stream Blackstar amp audio into your voice channel")
async def stream(ctx: discord.ApplicationContext) -> None:
    """Join the user's voice channel and start streaming audio via sounddevice."""
    if ctx.author.voice is None or ctx.author.voice.channel is None:  # type: ignore[union-attr]
        await ctx.respond("You must be in a voice channel first.")
        return

    if ctx.voice_client is not None:
        await ctx.respond("Already streaming. Use /stop first.")
        return

    s = _get_settings()
    device = find_device_by_name(s.audio_device)
    if device is None:
        await ctx.respond(f"Audio device matching '{s.audio_device}' not found.")
        return

    channel = ctx.author.voice.channel  # type: ignore[union-attr]
    voice_client = await channel.connect()

    source = BlackstarAudioSource(device, volume=s.volume)
    source.start()

    def _after_playback(error: Exception | None) -> None:
        source.cleanup()
        if error:
            logger.error("Playback error: %s", error)

    voice_client.play(source, signal_type="music", after=_after_playback)
    await ctx.respond(f"Streaming audio from **{device.name}** in {channel.name}.")


@bot.slash_command(description="Stop streaming and leave the voice channel")
async def stop(ctx: discord.ApplicationContext) -> None:
    """Stop playback and disconnect from the voice channel."""
    if ctx.voice_client is None:
        await ctx.respond("Not currently in a voice channel.")
        return
    vc = ctx.voice_client
    if vc.is_playing():
        vc.stop()
    elif isinstance(vc.source, BlackstarAudioSource):
        vc.source.cleanup()
    await vc.disconnect()
    await ctx.respond("Stopped streaming.")


def main() -> None:
    """Entry point for running the bot."""
    logging.basicConfig(level=logging.INFO)
    bot.run(_get_settings().discord_token)


if __name__ == "__main__":
    main()
