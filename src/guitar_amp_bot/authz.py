"""Authorization helpers shared by the bot entry points.

Every slash command exposes local audio hardware, so commands are restricted to
one Discord user: ``OWNER_ID`` when it is configured, otherwise the owner of
the bot's own Discord application. Checks compare numeric user IDs, never
usernames, because usernames are user-changeable.

Every unanswerable question denies the command. The bot may be in servers full
of people who can see its commands, so an owner check that cannot complete must
not resolve in the caller's favour.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

logger = logging.getLogger(__name__)

UNAUTHORIZED_MESSAGE = "You are not authorized to use this bot."


async def is_owner(ctx: discord.ApplicationContext, owner_id: int | None) -> bool:
    """Return whether the invoker of ``ctx`` may control this instance."""
    author_id = getattr(getattr(ctx, "author", None), "id", None)
    if not isinstance(author_id, int):
        return False
    if owner_id is not None:
        return author_id == owner_id
    return await _is_application_owner(ctx)


async def _is_application_owner(ctx: discord.ApplicationContext) -> bool:
    """Authorize against the Discord application's owner.

    Delegates to py-cord, which fetches the application once and then answers
    from cache, and covers team-owned applications. A lookup that fails denies
    the command.
    """
    checker = getattr(getattr(ctx, "bot", None), "is_owner", None)
    if checker is None:
        logger.warning("owner_lookup_unavailable: no bot on the command context")
        return False
    try:
        return bool(await checker(ctx.author))
    except Exception:
        logger.warning("owner_lookup_failed", exc_info=True)
        return False


async def require_owner(ctx: discord.ApplicationContext, owner_id: int | None) -> bool:
    """Authorize the invoker, replying privately when they are not the owner.

    Returns ``True`` when the command may proceed. Otherwise the refusal has
    already been sent and the caller must return immediately.
    """
    if await is_owner(ctx, owner_id):
        return True

    # Interpolated into the message rather than passed via ``extra`` (the
    # convention elsewhere in this package) so the refused user ID is visible
    # under the default logging format, not only to a structured handler.
    logger.warning(
        "unauthorized_command user_id=%s command=%s",
        getattr(getattr(ctx, "author", None), "id", None),
        getattr(getattr(ctx, "command", None), "name", "?"),
    )
    await ctx.respond(UNAUTHORIZED_MESSAGE, ephemeral=True)
    return False
