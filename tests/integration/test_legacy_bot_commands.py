"""Integration tests for the legacy FFmpeg bot entry point (mocked Discord client)."""

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import discord.voice
import pytest

from blackstar_bot.authz import UNAUTHORIZED_MESSAGE
from blackstar_bot.bot import stop, stream

OWNER_ID = 424242424242424242
INTRUDER_ID = 999999999999999999

_PLAY_SIGNATURE = inspect.signature(discord.voice.VoiceClient.play)


def _play_mock():
    """A play() mock that rejects arguments the real py-cord API would reject."""

    def _validate(*args, **kwargs):
        _PLAY_SIGNATURE.bind(MagicMock(), *args, **kwargs)

    return MagicMock(side_effect=_validate)


def _mock_settings():
    s = MagicMock()
    s.owner_id = OWNER_ID
    s.guild_id = 123456789012345678
    s.audio_device = "Blackstar"
    s.discord_token = "fake-token"
    return s


@pytest.fixture(autouse=True)
def reset_runtime_state():
    """Install mock settings so commands never touch a real environment."""
    import blackstar_bot.bot as bot_module

    bot_module._settings = _mock_settings()
    yield
    bot_module._settings = None


def _make_ctx(*, voice_client=None, author_id=OWNER_ID):
    ctx = AsyncMock()
    ctx.author = MagicMock()
    ctx.author.id = author_id
    ctx.author.voice.channel = AsyncMock()
    ctx.author.voice.channel.name = "General"
    ctx.author.voice.channel.connect = AsyncMock(return_value=voice_client or AsyncMock())
    ctx.voice_client = voice_client
    return ctx


@pytest.mark.parametrize("command", [stream, stop])
@pytest.mark.asyncio
async def test_legacy_commands_reject_non_owner(command):
    """Both legacy commands must refuse anyone but the configured owner."""
    ctx = _make_ctx(author_id=INTRUDER_ID)
    await command(ctx)
    ctx.respond.assert_awaited_once_with(UNAUTHORIZED_MESSAGE, ephemeral=True)
    ctx.author.voice.channel.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_stream_streams_configured_device_for_owner():
    """The owner streams the configured device — never one they supplied."""
    vc = AsyncMock()
    vc.play = _play_mock()
    ctx = _make_ctx(voice_client=None)
    ctx.author.voice.channel.connect = AsyncMock(return_value=vc)
    ffmpeg_source = MagicMock()

    with patch("blackstar_bot.bot.discord.FFmpegPCMAudio", return_value=ffmpeg_source) as factory:
        await stream(ctx)

    assert "Blackstar" in factory.call_args[0][0]
    vc.play.assert_called_once()
    ctx.respond.assert_awaited_once()
    assert "Blackstar" in ctx.respond.await_args[0][0]


@pytest.mark.asyncio
async def test_legacy_stream_requires_voice_channel():
    """The owner still has to be in a voice channel."""
    ctx = _make_ctx()
    ctx.author.voice = None
    await stream(ctx)
    ctx.respond.assert_awaited_once()
    assert "voice channel" in ctx.respond.await_args[0][0].lower()


@pytest.mark.asyncio
async def test_legacy_validation_reply_is_private():
    """The "join a voice channel" nudge concerns only the invoker."""
    ctx = _make_ctx()
    ctx.author.voice = None
    await stream(ctx)
    assert ctx.respond.await_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_legacy_successful_stream_stays_public():
    """Voice-channel members should see that a stream started."""
    vc = AsyncMock()
    vc.play = _play_mock()
    ctx = _make_ctx()
    ctx.author.voice.channel.connect = AsyncMock(return_value=vc)

    with patch("blackstar_bot.bot.discord.FFmpegPCMAudio", return_value=MagicMock()):
        await stream(ctx)

    assert ctx.respond.await_args.kwargs.get("ephemeral") is None


@pytest.mark.parametrize("command", [stream, stop])
@pytest.mark.asyncio
async def test_legacy_slow_commands_defer(command):
    """The legacy entry point must acknowledge before the voice handshake too."""
    vc = AsyncMock()
    vc.play = _play_mock()
    ctx = _make_ctx()
    ctx.author.voice.channel.connect = AsyncMock(return_value=vc)
    with patch("blackstar_bot.bot.discord.FFmpegPCMAudio", return_value=MagicMock()):
        await command(ctx)
    ctx.defer.assert_awaited_once_with(ephemeral=True)
