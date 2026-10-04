"""Tests for blackstar_bot.setup_wizard."""

import stat

import pytest

from blackstar_bot import setup_wizard
from blackstar_bot.device_finder import AudioDevice
from blackstar_bot.setup_wizard import parse_optional_id, quote, render_env, write_env

TOKEN = "fake-token"


def _devices():
    return [
        AudioDevice(
            index=0, name="MacBook Pro Microphone", max_input_channels=1, default_samplerate=48000.0
        ),
        AudioDevice(
            index=5, name="Blackstar ID:Core V4", max_input_channels=2, default_samplerate=48000.0
        ),
    ]


@pytest.fixture
def wizard(monkeypatch, tmp_path):
    """Drive the wizard with scripted answers in an isolated directory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(setup_wizard, "refresh_devices", lambda: None)
    monkeypatch.setattr(setup_wizard, "list_input_devices", _devices)
    monkeypatch.setattr(setup_wizard.getpass, "getpass", lambda _prompt: TOKEN)
    monkeypatch.setattr(setup_wizard, "_say", lambda _message: None)

    def _script(answers):
        remaining = list(answers)
        monkeypatch.setattr(setup_wizard, "_ask", lambda _prompt: remaining.pop(0))

    return _script


def test_quote_wraps_values_with_spaces():
    """Device names contain spaces, so values are always quoted."""
    assert quote("Blackstar ID:Core V4") == '"Blackstar ID:Core V4"'


def test_quote_escapes_quotes_and_backslashes():
    """Otherwise dotenv would read back something different."""
    assert quote('a"b\\c') == '"a\\"b\\\\c"'


def test_render_env_comments_out_unset_optional_keys():
    content = render_env({"DISCORD_TOKEN": "secret", "OWNER_ID": None})
    assert 'DISCORD_TOKEN="secret"' in content
    assert "# OWNER_ID=" in content
    assert content.endswith("\n")


@pytest.mark.parametrize("raw", ["", "   "])
def test_parse_optional_id_treats_blank_as_unset(raw):
    assert parse_optional_id(raw) is None


def test_parse_optional_id_accepts_a_snowflake():
    assert parse_optional_id(" 424242424242424242 ") == 424242424242424242


@pytest.mark.parametrize("raw", ["0", "-5"])
def test_parse_optional_id_rejects_non_positive(raw):
    with pytest.raises(ValueError, match="positive"):
        parse_optional_id(raw)


def test_parse_optional_id_rejects_junk():
    with pytest.raises(ValueError, match="invalid literal"):
        parse_optional_id("not-a-number")


def test_write_env_is_readable_only_by_its_owner(tmp_path):
    """The file holds a bot token, so other local accounts must not read it."""
    target = tmp_path / ".env"

    write_env(target, 'DISCORD_TOKEN="secret"\n')

    assert target.read_text(encoding="utf-8") == 'DISCORD_TOKEN="secret"\n'
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_main_writes_a_usable_env_with_optional_ids_unset(wizard, tmp_path):
    """Blank answers mean auto-detected owner and every server."""
    wizard(["", "", ""])

    setup_wizard.main()

    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f'DISCORD_TOKEN="{TOKEN}"' in written
    assert "# OWNER_ID=" in written
    assert "# GUILD_ID=" in written
    assert 'AUDIO_DEVICE="Blackstar"' in written
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600


def test_main_records_explicit_ids_and_a_picked_device(wizard, tmp_path):
    """Picking device 1 by number stores that device's full name."""
    wizard(["424242424242424242", "123456789012345678", "1"])

    setup_wizard.main()

    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert 'OWNER_ID="424242424242424242"' in written
    assert 'GUILD_ID="123456789012345678"' in written
    assert 'AUDIO_DEVICE="MacBook Pro Microphone"' in written


def test_main_leaves_an_existing_env_alone_when_declined(wizard, tmp_path):
    """Declining the overwrite must not touch the file or its backup."""
    env = tmp_path / ".env"
    env.write_text('DISCORD_TOKEN="original"\n', encoding="utf-8")
    wizard(["n"])

    setup_wizard.main()

    assert env.read_text(encoding="utf-8") == 'DISCORD_TOKEN="original"\n'
    assert not (tmp_path / ".env.bak").exists()


def test_main_backs_up_the_previous_env_before_replacing_it(wizard, tmp_path):
    wizard(["y", "", "", ""])

    (tmp_path / ".env").write_text('DISCORD_TOKEN="original"\n', encoding="utf-8")
    setup_wizard.main()

    assert (tmp_path / ".env.bak").read_text(encoding="utf-8") == 'DISCORD_TOKEN="original"\n'
    assert f'DISCORD_TOKEN="{TOKEN}"' in (tmp_path / ".env").read_text(encoding="utf-8")


def test_main_reprompts_after_an_invalid_id(wizard, tmp_path):
    """A typo must not abort the wizard."""
    wizard(["oops", "424242424242424242", "", ""])

    setup_wizard.main()

    assert 'OWNER_ID="424242424242424242"' in (tmp_path / ".env").read_text(encoding="utf-8")


def test_write_env_tightens_permissions_on_an_existing_file(tmp_path):
    """O_CREAT leaves an existing file's mode alone, so it is reset explicitly."""
    target = tmp_path / ".env"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o644)

    write_env(target, "new\n")

    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_text(encoding="utf-8") == "new\n"


def test_main_backup_is_readable_only_by_its_owner(wizard, tmp_path):
    """The replaced .env holds a token too, whatever mode it had before."""
    env = tmp_path / ".env"
    env.write_text('DISCORD_TOKEN="original"\n', encoding="utf-8")
    env.chmod(0o644)
    wizard(["y", "", "", ""])

    setup_wizard.main()

    assert stat.S_IMODE((tmp_path / ".env.bak").stat().st_mode) == 0o600
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_write_env_tightens_permissions_before_writing(tmp_path, monkeypatch):
    """The token must never sit in a file other accounts can read."""
    target = tmp_path / ".env"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o644)
    modes_at_write = []
    real_fdopen = setup_wizard.os.fdopen

    def _recording_fdopen(fd, *args, **kwargs):
        modes_at_write.append(stat.S_IMODE(target.stat().st_mode))
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(setup_wizard.os, "fdopen", _recording_fdopen)

    write_env(target, 'DISCORD_TOKEN="secret"\n')

    assert modes_at_write == [0o600]


def test_main_warns_about_sample_rate_for_a_typed_device_name(wizard, monkeypatch):
    """Typing a name must not skip the check that picking by number gets."""
    said = []
    monkeypatch.setattr(setup_wizard, "_say", said.append)
    monkeypatch.setattr(
        setup_wizard,
        "list_input_devices",
        lambda: [
            AudioDevice(
                index=3, name="USB Audio CODEC", max_input_channels=2, default_samplerate=44100.0
            )
        ],
    )
    wizard(["", "", "usb audio"])

    setup_wizard.main()

    assert any("44100 Hz" in message for message in said)
