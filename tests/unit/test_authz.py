"""Tests for blackstar_bot.authz."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from blackstar_bot.authz import UNAUTHORIZED_MESSAGE, is_owner, require_owner

OWNER_ID = 424242424242424242
INTRUDER_ID = 999999999999999999


def _ctx(author_id):
    ctx = AsyncMock()
    ctx.author = MagicMock()
    ctx.author.id = author_id
    ctx.command = MagicMock()
    ctx.command.name = "stream"
    return ctx


def test_is_owner_accepts_matching_id():
    assert is_owner(_ctx(OWNER_ID), OWNER_ID) is True


def test_is_owner_rejects_other_user():
    assert is_owner(_ctx(OWNER_ID + 1), OWNER_ID) is False


def test_is_owner_rejects_missing_author():
    ctx = AsyncMock()
    ctx.author = None
    assert is_owner(ctx, OWNER_ID) is False


def test_is_owner_rejects_non_integer_id():
    """A mock/string id must never satisfy the check."""
    assert is_owner(_ctx(str(OWNER_ID)), OWNER_ID) is False


@pytest.mark.asyncio
async def test_require_owner_allows_owner_without_responding():
    ctx = _ctx(OWNER_ID)
    assert await require_owner(ctx, OWNER_ID) is True
    ctx.respond.assert_not_awaited()


@pytest.mark.asyncio
async def test_require_owner_rejects_other_user_ephemerally():
    ctx = _ctx(OWNER_ID + 1)
    assert await require_owner(ctx, OWNER_ID) is False
    ctx.respond.assert_awaited_once_with(UNAUTHORIZED_MESSAGE, ephemeral=True)


@pytest.mark.asyncio
async def test_require_owner_logs_refused_user_in_rendered_message(caplog):
    """The audit line must name the user under the default format, not only via extra."""
    ctx = _ctx(INTRUDER_ID)
    with caplog.at_level(logging.WARNING, logger="blackstar_bot.authz"):
        await require_owner(ctx, OWNER_ID)

    record = caplog.records[-1]
    assert record.getMessage() == f"unauthorized_command user_id={INTRUDER_ID} command=stream"


@pytest.mark.asyncio
async def test_require_owner_logs_placeholders_when_context_is_incomplete():
    """A malformed context must still produce an audit line rather than raising."""
    ctx = AsyncMock()
    ctx.author = None
    ctx.command = None
    assert await require_owner(ctx, OWNER_ID) is False
