# Blackstar Discord Bot

Python bot that streams guitar audio from a Blackstar USB amp into a Discord voice channel.

## Features

- Stream live guitar audio from a Blackstar amplifier into Discord voice chat
- Two audio approaches: FFmpeg-based (`bot.py`) and sounddevice-based (`bot_sounddevice.py`)
- Automatic USB audio device discovery
- Configurable backend, device, and volume control
- Slash commands (`/stream`, `/stop`, `/status`, `/devices`, `/volume`)

## Requirements

- Python 3.12+
- macOS (for USB audio capture from Blackstar amp)
- PortAudio (primary sounddevice backend)
- FFmpeg (optional fallback backend)
- A Blackstar amplifier with USB audio output

On macOS, install the audio dependencies with Homebrew:

```bash
brew install portaudio ffmpeg
```

## Setup

```bash
# Clone and create virtual environment
git clone https://github.com/YOUR_USERNAME/blackstar-discord-bot
cd blackstar-discord-bot
python3.12 -m venv venv && source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
pre-commit install --hook-type commit-msg

# Configure environment
cp .env.example .env
# Edit .env and add your DISCORD_TOKEN, OWNER_ID, and GUILD_ID.
# AUDIO_BACKEND defaults to sounddevice; set it to ffmpeg only as a fallback.
```

`OWNER_ID` and `GUILD_ID` are required for access control — see
[Access control](#access-control) below. The bot refuses to start without
`OWNER_ID`.

## Usage

```bash
# Check that your Blackstar amp is detected
python scripts/list_devices.py

# Run the primary bot (sounddevice by default, FFmpeg fallback via AUDIO_BACKEND)
python -m blackstar_bot.bot_sounddevice

# Legacy FFmpeg-only entry point
python -m blackstar_bot.bot
```

In Discord, use:
- `/stream` — Join your voice channel and start streaming the configured audio device
- `/stop` — Stop streaming and disconnect
- `/status` — Show whether the bot is streaming
- `/devices` — List detected audio input devices
- `/volume` — Show or change the sounddevice playback volume

## Access control

Every command exposes local audio hardware, so all commands are restricted to a
single Discord user.

- `OWNER_ID` (**required**) — your numeric Discord user ID. Every command
  compares `ctx.author.id` against it and replies with a private refusal to
  anyone else. IDs are used rather than usernames because usernames can be
  changed. To find yours: Discord → Settings → Advanced → Developer Mode, then
  right-click your name → Copy User ID.
- `GUILD_ID` (recommended) — the numeric ID of your server. Slash commands are
  then registered only in that guild, so they do not appear anywhere else. Leave
  it unset only if you accept global registration; the bot logs a warning at
  startup when it is missing. Guild-scoped commands also register immediately
  instead of taking up to an hour to propagate.

`/stream` deliberately takes no arguments. The device and backend come from
`AUDIO_DEVICE` and `AUDIO_BACKEND`, so no Discord user — not even the owner —
can point the stream at another input on the host machine.

The bot token is a full credential: keep `.env` out of version control, and
reset the token in the Discord Developer Portal if it ever leaks.

### Reply visibility

Slash-command replies are public in the channel unless sent with
`ephemeral=True`. Because `/devices` and `/status` name local audio hardware,
and failure messages can carry filesystem paths from an exception, everything
except the "streaming started" and "stopped streaming" notices is sent
privately to the invoker. A private reply is labelled *Only you can see this*
in Discord.

The channel-wide notice posted when playback dies unexpectedly cannot be
ephemeral, so it carries no exception detail — that stays in the log.

### Audit log

Refused commands are logged as `unauthorized_command user_id=... command=...`,
naming the Discord user who was turned away. Logging goes to stderr and to a
rotating file at `LOG_FILE` (default `blackstar-bot.log`, 1 MB per file, 3
backups). Set `LOG_FILE=` to an empty value to log to stderr only. A configured
path that cannot be opened stops startup rather than silently dropping the audit
trail.

## Development

```bash
# Run linters and type checker
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/

# Run tests
pytest

# Run all checks (same as pre-commit)
pre-commit run --all-files
```

## Project Structure

```
src/blackstar_bot/
  __init__.py          # Package init
  bot.py               # Main bot (Approach B — FFmpeg)
  bot_sounddevice.py   # Alternative bot (Approach A — sounddevice)
  audio_source.py      # Custom AudioSource for sounddevice capture
  authz.py             # Owner-only command authorization
  device_finder.py     # Audio device discovery
  logging_setup.py     # stderr + rotating file logging
  config.py            # Pydantic-based settings from .env
tests/
  unit/                # Unit tests (mocked hardware)
  integration/         # Integration tests (mocked Discord client)
scripts/
  create_labels.sh     # Bulk-create GitHub labels
  list_devices.py      # List available audio input devices
```

## Configuration & Troubleshooting

`AUDIO_DEVICE` is a case-insensitive substring match, so `Blackstar` should match
typical Blackstar USB devices. If streaming fails, run `python scripts/list_devices.py`
or `/devices` to confirm the amp is visible. The sounddevice backend requires a
48 kHz input device; wrong-rate devices are rejected before playback starts.

Set `DEBUG_CONFIG=true` to log the selected backend, device, and volume without
printing the Discord token. Linux and Windows FFmpeg paths are best-effort and
should be verified on real hardware before relying on them.

## License

MIT
