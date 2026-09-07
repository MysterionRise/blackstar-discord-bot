"""Main Discord bot — Approach B (FFmpeg-based audio streaming)."""

from __future__ import annotations

import logging
import sys
from typing import Any

import discord
from pydantic import ValidationError

from blackstar_bot.authz import require_owner
from blackstar_bot.config import Settings
from blackstar_bot.logging_setup import configure_logging

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
    """Join the owner's voice channel and start streaming audio via FFmpeg."""
    if not await require_owner(ctx, _get_settings().owner_id):
        return

    # The voice handshake outlasts Discord's 3s interaction deadline.
    await ctx.defer(ephemeral=True)

    voice_state = getattr(ctx.author, "voice", None)
    if voice_state is None or voice_state.channel is None:
        await ctx.respond("You must be in a voice channel first.", ephemeral=True)
        return

    if ctx.voice_client is not None:
        await ctx.respond("Already streaming. Use /stop first.", ephemeral=True)
        return

    channel = voice_state.channel
    voice_client = await channel.connect()

    s = _get_settings()
    input_source, before_options = _ffmpeg_input_args(s.audio_device)
    source = discord.FFmpegPCMAudio(input_source, before_options=before_options)
    voice_client.play(source, signal_type="music")
    await ctx.respond(f"Streaming audio from **{s.audio_device}** in {channel.name}.")


@bot.slash_command(
    description="Stop streaming and leave the voice channel",
    guild_ids=GUILD_IDS,
)
async def stop(ctx: discord.ApplicationContext) -> None:
    """Stop playback and disconnect from the voice channel."""
    if not await require_owner(ctx, _get_settings().owner_id):
        return

    await ctx.defer(ephemeral=True)

    if ctx.voice_client is None:
        await ctx.respond("Not currently in a voice channel.", ephemeral=True)
        return
    vc = ctx.voice_client
    if vc.is_playing():
        vc.stop()
    await vc.disconnect()
    await ctx.respond("Stopped streaming.")


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
