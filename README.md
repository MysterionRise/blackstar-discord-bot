# Blackstar Discord Bot

Python bot that streams guitar audio from a Blackstar USB amp into a Discord voice channel.

## Features

- Stream live guitar audio from a Blackstar amplifier into Discord voice chat
- Two capture backends in one bot: sounddevice (default) and FFmpeg (`AUDIO_BACKEND=ffmpeg`)
- Automatic USB audio device discovery
- Configurable backend, device, and volume control
- Slash commands (`/stream`, `/stop`, `/status`, `/devices`, `/volume`)

## Requirements

- Python 3.12+
- py-cord 2.8+ (earlier versions cannot connect to voice: Discord has
  enforced the DAVE end-to-end-encryption protocol since 2 March 2026 and
  closes voice websockets from older clients with code 4017)
- macOS (for USB audio capture from Blackstar amp)
- PortAudio (primary sounddevice backend)
- FFmpeg (optional fallback backend)
- A Blackstar amplifier with USB audio output

On macOS, install the audio dependencies with Homebrew:

```bash
brew install portaudio ffmpeg
```

## Run your own instance

Everyone runs their own bot: your own Discord application, your own token, on
your own machine. That is what keeps the audio private — a bot process can only
capture the devices on the host it runs on, and only its owner can start a
stream. Your amp is never reachable from someone else's instance, whatever
servers you share.

```bash
git clone https://github.com/MysterionRise/blackstar-discord-bot
cd blackstar-discord-bot
python3.12 -m venv venv && source venv/bin/activate
pip install -e .

blackstar-bot-setup      # asks for your token and picks the audio device
blackstar-bot            # start the bot
```

The wizard prints how to create the application. Two settings there matter:

- **Reset Token** on the Bot tab gives you the token the wizard asks for.
- **Public Bot**, on the same tab, should be turned **off** so nobody but you
  can add your bot to a server.

On startup the bot logs an `invite_url=` line. Open it to add the bot to a
server — repeat for each server you want it in — then join a voice channel and
run `/stream`. You need "Manage Server" on any server you add it to.

Other members of those servers will see the commands but cannot use them: every
command is refused for anyone who is not the owner of that instance.

## Setup

For development, or to configure without the wizard:

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
# Edit .env and add your DISCORD_TOKEN. OWNER_ID and GUILD_ID are optional.
# AUDIO_BACKEND defaults to sounddevice; set it to ffmpeg only as a fallback.
```

`DISCORD_TOKEN` is the only required setting. `OWNER_ID` and `GUILD_ID` shape
access control — see [Access control](#access-control) below.

## Usage

```bash
# Check that your Blackstar amp is detected
python scripts/list_devices.py

# Run the bot (sounddevice by default, FFmpeg fallback via AUDIO_BACKEND)
blackstar-bot
```

`blackstar-bot-sd` and `python -m blackstar_bot.bot_sounddevice` start the same
bot. `blackstar-bot-setup` writes `.env` interactively.

In Discord, use:
- `/stream` — Join your voice channel and start streaming the configured audio device
- `/stop` — Stop streaming and disconnect
- `/status` — Show whether the bot is streaming
- `/devices` — List detected audio input devices
- `/volume` — Show or change the sounddevice playback volume

The bot also stops on its own 30 seconds after you leave its voice channel, or
after the channel empties, so the amp is never left broadcasting to nobody (or
to people you left behind). Rejoining within those 30 seconds keeps it running.

There is only one amp, so there is only ever one stream. While it runs,
`/stream` is refused everywhere, and `/stop`, `/status` and `/volume` work from
any server the bot is in.

## Access control

Every command exposes local audio hardware, so all commands are restricted to a
single Discord user.

- `OWNER_ID` (optional) — your numeric Discord user ID. Left unset, the bot
  authorizes the owner of its own Discord application, which is whoever created
  the token: you. Set it explicitly to pin authorization to one account, which
  is worth doing if the application is owned by a Discord **team**, because
  every team member counts as an owner otherwise. The bot warns at startup when
  it finds a team. To find your ID: Discord → Settings → Advanced → Developer
  Mode, then right-click your name → Copy User ID.
- `GUILD_ID` (optional) — the numeric ID of a single server. Slash commands are
  then registered only there, and they register immediately instead of taking
  up to an hour to propagate. Leave it unset to use the bot in every server you
  add it to, which is the normal setup when the bot is yours alone.

Either way the check compares numeric user IDs, never usernames, because
usernames can be changed. An owner check that cannot be completed — say Discord
is unreachable during the application lookup — refuses the command rather than
allowing it.

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

### Capture device safety

Only audio that can be positively attributed to `AUDIO_DEVICE` is ever sent to
Discord. This matters because PortAudio caches its device list and identifies
devices by positional index: when the amp is unplugged, its index can be
reassigned to another input, and a naive capture would quietly continue on the
built-in microphone and broadcast the room.

The sounddevice backend therefore:

- re-enumerates devices before opening a stream, so an already-unplugged amp is
  not matched from a stale list;
- verifies the live device name at the index it just opened, and refuses to
  stream on a mismatch;
- mutes capture — sending silence, never substitute audio — as soon as the
  device stops delivering frames, the stream is aborted, or PortAudio reports an
  error;
- re-acquires the amp **by name** and resumes automatically, so a knocked cable
  needs no new `/stream`. `/status` reports this state;
- gives up after 60 seconds, stops the stream, leaves the voice channel, and
  posts a channel notice that deliberately does not name your hardware.

The FFmpeg backend passes the device name to FFmpeg, which fails rather than
capturing a different input, so it does not leak either — but it does not
re-acquire the device. `AUDIO_BACKEND=sounddevice`, the default, is the
supported path.

### Audit log

Refused commands are logged as `unauthorized_command user_id=... command=...`,
naming the Discord user who was turned away. Logging goes to stderr and to a
rotating file at `LOG_FILE` (default `blackstar-bot.log`, 1 MB per file, 3
backups). Set `LOG_FILE=` to an empty value to log to stderr only. A configured
path that cannot be opened stops startup rather than silently dropping the audit
trail.

## Docker (Linux hosts only, experimental)

Docker Desktop on macOS and Windows runs containers in a Linux VM that cannot
reach host USB audio, so the amp is invisible from inside a container there. On
a Mac, install natively as above. On a Linux host, ALSA can be passed through:

```bash
blackstar-bot-setup        # or write .env by hand
docker compose up --build  # logs go to stderr: docker compose logs -f
```

`docker-compose.yml` passes `/dev/snd` into the container and joins the `audio`
group. If the amp is not detected, compare the host's audio GID
(`getent group audio`) with the container's and set `group_add` to that number.

This path is not verified against real amp hardware — the image builds and the
audio stack loads, but capture itself has only been exercised natively on
macOS.

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
  bot_sounddevice.py   # The bot: slash commands, sounddevice or FFmpeg capture
  audio_source.py      # Custom AudioSource for sounddevice capture
  authz.py             # Owner-only command authorization
  device_finder.py     # Audio device discovery
  logging_setup.py     # stderr + rotating file logging
  config.py            # Pydantic-based settings from .env
  startup.py           # Owner resolution + invite link logging
  setup_wizard.py      # Interactive .env setup (blackstar-bot-setup)
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
