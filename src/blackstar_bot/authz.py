"""Authorization helpers shared by the bot entry points.

Every slash command exposes local audio hardware, so commands are restricted to
the single Discord user configured as ``OWNER_ID``. Checks compare numeric user
IDs, never usernames, because usernames are user-changeable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

logger = logging.getLogger(__name__)

UNAUTHORIZED_MESSAGE = "You are not authorized to use this bot."


def is_owner(ctx: discord.ApplicationContext, owner_id: int) -> bool:
    """Return whether the invoker of ``ctx`` is the configured owner."""
    author_id = getattr(getattr(ctx, "author", None), "id", None)
    return isinstance(author_id, int) and author_id == owner_id


async def require_owner(ctx: discord.ApplicationContext, owner_id: int) -> bool:
    """Authorize the invoker, replying privately when they are not the owner.

    Returns ``True`` when the command may proceed. Otherwise the refusal has
    already been sent and the caller must return immediately.
    """
    if is_owner(ctx, owner_id):
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
