"""Interactive first-run setup: writes a .env for your own bot instance."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

from guitar_amp_bot.device_finder import (
    DEFAULT_INPUT_CHANNELS,
    AmbiguousDeviceError,
    AudioDevice,
    capture_problem,
    format_input_channels,
    list_input_devices,
    parse_input_channels,
    refresh_devices,
    select_device,
)

ENV_PATH = Path(".env")
BACKUP_PATH = Path(".env.bak")
PORTAL_URL = "https://discord.com/developers/applications"

# The token is a full credential; keep it off other accounts on this machine.
ENV_FILE_MODE = 0o600

INTRO = f"""
Guitar amp bot setup
====================

This configures one bot instance for you alone: it streams the amp (or any
USB audio device) plugged into *this* machine, and only you can run its
commands.

First create your own Discord application:

  1. Open {PORTAL_URL} and click "New Application".
  2. Open the "Bot" tab, then "Reset Token", and copy the token.
  3. On the same tab turn OFF "Public Bot", so nobody else can add your bot
     to a server.

The bot logs its own invite link on startup, so you do not need it yet.
"""

OUTRO = """
Done. Next steps:

  1. Start the bot:  guitar-amp-bot
  2. Copy the invite_url line it logs and open it to add the bot to a server.
  3. Join a voice channel and run /stream.
"""


def quote(value: str) -> str:
    """Quote a value for a .env file, escaping what dotenv would re-read."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_env(values: dict[str, str | None]) -> str:
    """Render .env content, writing unset optional keys as comments."""
    lines = ["# Written by guitar-amp-bot-setup. Keep this file out of git."]
    for key, value in values.items():
        if value is None:
            lines.append(f"# {key}=")
        else:
            lines.append(f"{key}={quote(value)}")
    return "\n".join(lines) + "\n"


def parse_optional_id(raw: str) -> int | None:
    """Parse an optional positive Discord snowflake, blank meaning unset."""
    text = raw.strip()
    if not text:
        return None
    value = int(text)
    if value <= 0:
        msg = "must be a positive number"
        raise ValueError(msg)
    return value


def write_env(path: Path, content: str) -> None:
    """Write *content* to *path*, readable only by the current user."""
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, ENV_FILE_MODE)
    # A pre-existing file keeps its old mode through O_CREAT, so tighten it
    # before the token is written rather than after.
    os.chmod(path, ENV_FILE_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)


def _say(message: str) -> None:
    print(message)  # noqa: T201


def _ask(prompt: str) -> str:
    return input(prompt)


def _confirm(prompt: str) -> bool:
    return _ask(f"{prompt} [y/N]: ").strip().lower() in {"y", "yes"}


def _ask_optional_id(label: str, note: str) -> int | None:
    while True:
        _say(note)
        try:
            return parse_optional_id(_ask(f"{label} (blank to skip): "))
        except ValueError:
            _say(f"  Not a valid {label}. Try again.\n")


def _ask_token() -> str:
    while True:
        # getpass so the credential never lands in the scrollback.
        token = getpass.getpass("Bot token (input hidden): ").strip()
        if token:
            return token
        _say("  A token is required.\n")


def _ask_device_name(prompt: str) -> str:
    while True:
        name = _ask(prompt).strip()
        if name:
            return name
        # A blank query is a substring of every device name, so it never saves.
        _say("  A device is required.")


def _ask_device() -> tuple[str, AudioDevice | None]:
    """Return the ``AUDIO_DEVICE`` query, and the device it names if one is plugged in."""
    refresh_devices()
    devices = list_input_devices()
    if not devices:
        _say(
            "\nNo audio input devices detected. Plug in the amp and re-run this, "
            "or enter a name to match later."
        )
        return _ask_device_name("Device name: "), None

    _say("\nDetected audio inputs:")
    for position, device in enumerate(devices, start=1):
        hostapi = f"{device.hostapi}, " if device.hostapi else ""
        _say(f"  {position}. {device.name} ({hostapi}{device.default_samplerate:g} Hz default)")

    while True:
        query = _ask_device_name("\nPick a number, or type a name to match: ")
        if query.isdigit():
            chosen = int(query)
            if not 1 <= chosen <= len(devices):
                _say("  No device with that number.")
                continue
            device = devices[chosen - 1]
            return device.name, device
        try:
            matched = select_device(devices, query)
        except AmbiguousDeviceError as exc:
            _say(f"  '{query}' matches several inputs; the bot would refuse it:")
            for name in exc.candidates:
                _say(f"    - {name}")
            _say("  Pick a number or type a more specific name.")
            continue
        return query, matched


def _ask_input_channels(device: AudioDevice) -> tuple[int, ...]:
    """Ask which of *device*'s inputs to stream; a single input is streamed as mono."""
    if device.max_input_channels == 1:
        _say(f"\n'{device.name}' has a single input, so it is streamed as mono.")
        return (1,)

    default = format_input_channels(DEFAULT_INPUT_CHANNELS)
    _say(
        f"\n'{device.name}' has {device.max_input_channels} inputs. Amps and modellers "
        f"send stereo on inputs {default}: press Enter. On an audio interface, type the "
        "input your instrument is plugged into (e.g. 1) to hear it in both ears."
    )
    while True:
        raw = _ask(f"Inputs to stream [{default}]: ").strip()
        if not raw:
            return DEFAULT_INPUT_CHANNELS
        try:
            channels = parse_input_channels(raw)
        except ValueError as exc:
            _say(f"  {exc}. Try again.")
            continue
        if max(channels) > device.max_input_channels:
            _say(f"  It only has inputs 1 to {device.max_input_channels}. Try again.")
            continue
        return channels


def _warn_if_unusable(device: AudioDevice, input_channels: tuple[int, ...]) -> None:
    problem = capture_problem(device, input_channels)
    if problem is not None:
        _say(f"  Note: {problem} The sounddevice backend will refuse it.")


def main() -> None:
    """Collect configuration interactively and write .env."""
    _say(INTRO)

    if ENV_PATH.exists() and not _confirm(f"{ENV_PATH} already exists. Replace it?"):
        _say("Left your existing .env alone. Nothing was changed.")
        return

    token = _ask_token()
    owner_id = _ask_optional_id(
        "OWNER_ID",
        "\nOWNER_ID restricts commands to one Discord user. Leave it blank and "
        "the bot authorizes whoever owns its Discord application — you.",
    )
    guild_id = _ask_optional_id(
        "GUILD_ID",
        "\nGUILD_ID registers the commands in a single server. Leave it blank "
        "to use the bot in every server you add it to.",
    )
    device_query, device = _ask_device()
    input_channels: tuple[int, ...] | None = None
    if device is not None:
        input_channels = _ask_input_channels(device)
        _warn_if_unusable(device, input_channels)

    if ENV_PATH.exists():
        # The old file holds a token too: the backup gets the same 0600 mode.
        write_env(BACKUP_PATH, ENV_PATH.read_text(encoding="utf-8"))
        _say(f"\nBacked up your previous config to {BACKUP_PATH}.")

    write_env(
        ENV_PATH,
        render_env(
            {
                "DISCORD_TOKEN": token,
                "OWNER_ID": None if owner_id is None else str(owner_id),
                "GUILD_ID": None if guild_id is None else str(guild_id),
                "AUDIO_DEVICE": device_query,
                "INPUT_CHANNELS": (
                    None if input_channels is None else format_input_channels(input_channels)
                ),
                "AUDIO_BACKEND": "sounddevice",
            }
        ),
    )
    _say(f"\nWrote {ENV_PATH} (readable only by you).")
    _say(OUTRO)


if __name__ == "__main__":
    main()
