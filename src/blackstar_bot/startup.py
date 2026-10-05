"""Startup announcements shared by the bot entry points."""

from __future__ import annotations

import logging
import weakref
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from blackstar_bot.config import Settings

logger = logging.getLogger(__name__)

# All the bot needs: join a voice channel and talk in it.
INVITE_PERMISSIONS = discord.Permissions(connect=True, speak=True)
INVITE_SCOPES = ("bot", "applications.commands")

# on_ready fires again after every gateway reconnect; announce once per bot.
_announced: weakref.WeakSet[discord.Bot] = weakref.WeakSet()


async def announce_startup(bot: discord.Bot, settings: Settings) -> None:
    """Log who may control this instance, and the link that invites it."""
    if bot in _announced:
        return
    _announced.add(bot)
    await resolve_owner(bot, settings)
    log_invite_url(bot)


async def resolve_owner(bot: discord.Bot, settings: Settings) -> None:
    """Make sure the owner is known before the first command arrives.

    Priming py-cord's cache here keeps the owner lookup off the command path,
    where an HTTP round trip would eat into Discord's 3s interaction deadline.
    """
    if settings.owner_id is not None:
        logger.info("owner_resolved source=OWNER_ID owner_id=%s", settings.owner_id)
        return

    try:
        app = await bot.application_info()
    except Exception:
        # Commands stay refused until this succeeds, which is the safe side.
        logger.warning("owner_lookup_failed: set OWNER_ID to avoid the lookup", exc_info=True)
        return

    team = getattr(app, "team", None)
    if team is not None:
        member_ids = {member.id for member in team.members}
        bot.owner_ids = member_ids
        logger.warning(
            "owner_is_team members=%d — every team member can control this bot "
            "and its audio hardware; set OWNER_ID to restrict it to one person",
            len(member_ids),
        )
        return

    owner_id = getattr(getattr(app, "owner", None), "id", None)
    if owner_id is None:
        logger.warning("owner_unresolved: Discord returned no application owner; set OWNER_ID")
        return

    bot.owner_id = owner_id
    logger.info("owner_resolved source=application owner_id=%s", owner_id)


def log_invite_url(bot: discord.Bot) -> None:
    """Log the OAuth2 URL that adds this bot to a server."""
    client_id = getattr(getattr(bot, "user", None), "id", None)
    if client_id is None:
        return

    url = discord.utils.oauth_url(
        client_id,
        permissions=INVITE_PERMISSIONS,
        scopes=INVITE_SCOPES,
    )
    logger.info("invite_url=%s", url)
