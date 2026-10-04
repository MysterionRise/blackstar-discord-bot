"""Tests for blackstar_bot.startup."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from blackstar_bot.startup import announce_startup, log_invite_url, resolve_owner

OWNER_ID = 424242424242424242
TEAM_MEMBER_IDS = (111111111111111111, 222222222222222222)
CLIENT_ID = 555555555555555555

# connect (1 << 20) + speak (1 << 21)
EXPECTED_PERMISSIONS = "3145728"


def _settings(owner_id=None):
    settings = MagicMock()
    settings.owner_id = owner_id
    return settings


def _bot(*, app=None, user_id=CLIENT_ID):
    bot = MagicMock()
    bot.owner_id = None
    bot.owner_ids = set()
    bot.user.id = user_id
    bot.application_info = AsyncMock(return_value=app)
    return bot


def _app(*, owner_id=None, team_member_ids=None):
    app = MagicMock()
    if team_member_ids is None:
        app.team = None
        app.owner.id = owner_id
    else:
        app.team.members = [MagicMock(id=member_id) for member_id in team_member_ids]
    return app


@pytest.mark.asyncio
async def test_configured_owner_id_needs_no_application_call():
    bot = _bot()
    await resolve_owner(bot, _settings(owner_id=OWNER_ID))
    bot.application_info.assert_not_awaited()


@pytest.mark.asyncio
async def test_application_owner_is_cached_on_the_bot():
    """Priming py-cord's cache keeps the lookup off the command path."""
    bot = _bot(app=_app(owner_id=OWNER_ID))

    await resolve_owner(bot, _settings())

    assert bot.owner_id == OWNER_ID


@pytest.mark.asyncio
async def test_team_owned_application_authorizes_every_member_with_a_warning(caplog):
    """A team-owned app is a wider grant than people expect, so it is flagged."""
    bot = _bot(app=_app(team_member_ids=TEAM_MEMBER_IDS))

    with caplog.at_level(logging.WARNING, logger="blackstar_bot.startup"):
        await resolve_owner(bot, _settings())

    assert bot.owner_ids == set(TEAM_MEMBER_IDS)
    assert any("owner_is_team" in record.message for record in caplog.records)
    assert any("OWNER_ID" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_failed_lookup_leaves_no_owner_configured(caplog):
    """Without an owner, commands stay refused — the safe side."""
    bot = _bot()
    bot.application_info = AsyncMock(side_effect=RuntimeError("Discord is down"))

    with caplog.at_level(logging.WARNING, logger="blackstar_bot.startup"):
        await resolve_owner(bot, _settings())

    assert bot.owner_id is None
    assert any("owner_lookup_failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_missing_application_owner_is_reported(caplog):
    bot = _bot(app=_app(owner_id=None))

    with caplog.at_level(logging.WARNING, logger="blackstar_bot.startup"):
        await resolve_owner(bot, _settings())

    assert bot.owner_id is None
    assert any("owner_unresolved" in record.message for record in caplog.records)


def test_invite_url_requests_only_voice_permissions(caplog):
    """The invite asks for connect+speak and nothing more."""
    with caplog.at_level(logging.INFO, logger="blackstar_bot.startup"):
        log_invite_url(_bot())

    logged = caplog.records[-1].getMessage()
    assert str(CLIENT_ID) in logged
    assert f"permissions={EXPECTED_PERMISSIONS}" in logged
    assert "applications.commands" in logged


def test_invite_url_is_skipped_before_login(caplog):
    bot = _bot()
    bot.user = None

    with caplog.at_level(logging.INFO, logger="blackstar_bot.startup"):
        log_invite_url(bot)

    assert not caplog.records


@pytest.mark.asyncio
async def test_announce_startup_reports_owner_and_invite(caplog):
    bot = _bot(app=_app(owner_id=OWNER_ID))

    with caplog.at_level(logging.INFO, logger="blackstar_bot.startup"):
        await announce_startup(bot, _settings())

    messages = [record.getMessage() for record in caplog.records]
    assert any("owner_resolved" in message for message in messages)
    assert any("invite_url=" in message for message in messages)
