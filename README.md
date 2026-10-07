# Discord Guitar Amp Bot

Python bot that streams your amp into a Discord voice channel: plug a USB amp,
modeller or audio interface into your computer, run `/stream`, and the bot
joins your voice channel and plays it, in stereo, as its own participant.

It was built for (and verified with) a Blackstar ID:Core, but it works with
anything your computer sees as an audio input: other USB amps and modellers
(Boss Katana, Line 6, Positive Grid Spark, Fender Mustang and the like), any
USB audio interface, and keyboards, synths or drum machines with USB audio.

Why a bot, rather than picking the amp as your Discord microphone:

- Discord's microphone path is tuned for speech. Noise suppression, echo
  cancellation, automatic gain and voice-activity gating cut off or colour
  sustained notes; the bot's stream skips all of it.
- You keep talking on your normal mic while the amp plays separately, and
  listeners get their own volume slider for it.
- It is stereo, and it never falls back to broadcasting the room: see
  [Capture device safety](#capture-device-safety).

Discord adds a few hundred milliseconds of delay, so this is for playing *for*
people (showing a tone, lessons, a music community) rather than playing in
time *with* them; tools such as Jamulus or SonoBus cover that.

## Features

- Stream live audio from a USB amp or audio interface into Discord voice chat
- Two capture backends in one bot: sounddevice (default) and FFmpeg (`AUDIO_BACKEND=ffmpeg`)
- Automatic USB audio device discovery
- Configurable backend, device, and volume control
- Slash commands (`/stream`, `/stop`, `/status`, `/devices`, `/volume`)

## Requirements

- Python 3.12+
- py-cord 2.8+ (earlier versions cannot connect to voice: Discord has
  enforced the DAVE end-to-end-encryption protocol since 2 March 2026 and
  closes voice websockets from older clients with code 4017)
- An amp, modeller or audio interface with USB audio output, plugged into the
  machine that runs the bot
- PortAudio, for the default sounddevice backend
- FFmpeg, only for the optional FFmpeg backend

| Platform | Status | Audio dependencies |
|---|---|---|
| macOS | Verified with a real amp (Blackstar ID:Core V4); the primary platform | `brew install portaudio ffmpeg` |
| Linux | Expected to work (ALSA); not yet verified with an amp | `sudo apt install libportaudio2 ffmpeg` |
| Windows | Expected to work (WASAPI); not yet verified with an amp | None: the sounddevice wheel bundles PortAudio. FFmpeg on `PATH` only for the FFmpeg backend |

The sounddevice backend is the same code on every platform. Only its device
naming and the FFmpeg backend's input format differ per platform.

| Hardware | Status |
|---|---|
| Blackstar ID:Core V4 | Verified on macOS |
| Other USB amps and modellers, USB audio interfaces, keyboards and synths | Expected to work if they offer a stereo input that opens at 48 kHz; please report results in an issue |

On macOS, the app the bot runs from (Terminal, iTerm, …) needs microphone
access: see [macOS microphone permission](#macos-microphone-permission).

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

guitar-amp-bot-setup     # asks for your token and picks the audio device
guitar-amp-bot           # start the bot
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
git clone https://github.com/MysterionRise/blackstar-discord-bot
cd blackstar-discord-bot
python3.12 -m venv venv && source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
pre-commit install --hook-type commit-msg

# Configure environment
cp .env.example .env
# Edit .env: set DISCORD_TOKEN and AUDIO_DEVICE. OWNER_ID and GUILD_ID are optional.
# AUDIO_BACKEND defaults to sounddevice; set it to ffmpeg only as a fallback.
```

`DISCORD_TOKEN` and `AUDIO_DEVICE` are the only required settings. `OWNER_ID`
and `GUILD_ID` shape access control — see [Access control](#access-control) below.

### Settings

Settings are read from the environment, or from `.env` in the directory the bot
is started from.

| Variable | Default | Meaning |
|---|---|---|
| `DISCORD_TOKEN` | required | Bot token from the Discord Developer Portal |
| `OWNER_ID` | owner of the application | The one Discord user ID allowed to run commands |
| `GUILD_ID` | unset (every server) | Register commands in this one server only |
| `AUDIO_DEVICE` | required | Capture device; see [Choosing the device](#choosing-the-device). The wizard fills it in |
| `AUDIO_BACKEND` | `sounddevice` | `sounddevice`, or `ffmpeg` as a fallback |
| `VOLUME` | `1.0` | Playback volume multiplier, `0.0` to `5.0`. `/volume` overrides it until the bot restarts |
| `DEBUG_CONFIG` | `false` | Log the backend, device and volume when a stream starts (never the token) |
| `LOG_FILE` | `guitar-amp-bot.log` | Rotating log file; empty means stderr only |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

### Console commands

| Command | Does |
|---|---|
| `guitar-amp-bot` | Run the bot (same as `python -m guitar_amp_bot.bot_sounddevice`) |
| `guitar-amp-bot-setup` | Interactive wizard that writes `.env` |
| `blackstar-bot`, `blackstar-bot-sd`, `blackstar-bot-setup` | Names from before the rename, kept for existing setups |
| `python scripts/list_devices.py` | List the audio inputs PortAudio can see |

## Usage

```bash
# Check that your amp is detected
python scripts/list_devices.py

# Run the bot (sounddevice by default, FFmpeg fallback via AUDIO_BACKEND)
guitar-amp-bot
```

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

The FFmpeg backend hands `AUDIO_DEVICE` to FFmpeg as an exact device name. FFmpeg
fails rather than capturing a different input, so this backend does not leak
audio either, but it does not re-acquire the device. `AUDIO_BACKEND=sounddevice`,
the default, is the supported path.

### Audit log

Refused commands are logged as `unauthorized_command user_id=... command=...`,
naming the Discord user who was turned away. Logging goes to stderr and to a
rotating file at `LOG_FILE` (default `guitar-amp-bot.log`, 1 MB per file, 3
backups). Set `LOG_FILE=` to an empty value to log to stderr only. A configured
path that cannot be opened stops startup rather than silently dropping the audit
trail.

Log lines carry their context as `key=value` fields (for example
`voice_connect_failed channel=General attempt=2`). Set `LOG_LEVEL` to `DEBUG`,
`INFO` (default), `WARNING` or `ERROR` to control how much is written.

## Docker (Linux hosts only, experimental)

Docker Desktop on macOS and Windows runs containers in a Linux VM that cannot
reach host USB audio, so the amp is invisible from inside a container there. On
a Mac, install natively as above. On a Linux host, ALSA can be passed through:

```bash
guitar-amp-bot-setup       # or write .env by hand
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

## Releasing

1. In `CHANGELOG.md`, turn the `Unreleased` heading into the new version with a
   date, e.g. `## [0.2.0] - 2026-11-01`.
2. Set the same version in `pyproject.toml` (or run `cz bump`, which also creates
   the tag). `pyproject.toml` is the only place the version lives.
3. Push the tag: `git tag v0.2.0 && git push origin v0.2.0`.

The release workflow publishes that version's `CHANGELOG.md` section as the
GitHub Release notes, and fails if the tag and `pyproject.toml` disagree.

## Project Structure

```
src/guitar_amp_bot/
  __init__.py          # Package init
  bot_sounddevice.py   # The bot: slash commands, sounddevice or FFmpeg capture
  audio_source.py      # Custom AudioSource for sounddevice capture
  authz.py             # Owner-only command authorization
  device_finder.py     # Audio device discovery
  logging_setup.py     # stderr + rotating file logging
  config.py            # Pydantic-based settings from .env
  startup.py           # Owner resolution + invite link logging
  setup_wizard.py      # Interactive .env setup (guitar-amp-bot-setup)
tests/
  unit/                # Unit tests (mocked hardware)
  integration/         # Integration tests (mocked Discord client)
scripts/
  create_labels.sh     # Bulk-create GitHub labels
  list_devices.py      # List available audio input devices
  release_notes.py     # CHANGELOG.md section for a release tag (used by CI)
```

## Configuration & Troubleshooting

### Choosing the device

There is no default device: `guitar-amp-bot-setup` lists your inputs and writes
the one you pick, and the bot refuses to start without `AUDIO_DEVICE` rather
than guess.

With the sounddevice backend, `AUDIO_DEVICE` matches device names case-insensitively. An exact name wins;
otherwise it is a substring match, so `Blackstar` matches a Blackstar ID:Core
and `Katana` a Boss Katana. If it matches several different inputs, `/stream` refuses and lists
them, and `AUDIO_DEVICE` should be set to one of those exact names. When the same
device appears under several host APIs (Windows lists each input under MME,
DirectSound and WASAPI), the native API is preferred: WASAPI, Core Audio or ALSA
over MME.

If streaming fails, run `/devices` (it re-scans for hot-plugged devices when
nothing is streaming) or `python scripts/list_devices.py` to confirm the amp is
visible. The sounddevice backend needs a stereo input that PortAudio can open at
48 kHz; the device's default rate may differ. Devices that cannot are rejected
before playback starts, with the reason.

With `AUDIO_BACKEND=ffmpeg` there is no matching at all: `AUDIO_DEVICE` must be
the exact name FFmpeg uses on that platform, which may differ from what
`/devices` shows.

| Platform | FFmpeg input | `AUDIO_DEVICE` is | List devices with |
|---|---|---|---|
| macOS | AVFoundation `:<device>` | the device name or index | `ffmpeg -f avfoundation -list_devices true -i ""` |
| Linux | ALSA `hw:<device>` | the card number or ID, e.g. `1` or `V4` | `arecord -l` |
| Windows | DirectShow `audio=<device>` | the full device name | `ffmpeg -list_devices true -f dshow -i dummy` |

Set `DEBUG_CONFIG=true` to log the selected backend, device, and volume without
printing the Discord token. The Linux and Windows FFmpeg paths are best-effort
and should be verified on real hardware before relying on them.

### macOS microphone permission

macOS asks before any app records an audio input, including a USB amp. The
permission belongs to the app the bot runs in (Terminal, iTerm, VS Code, …), not
to the bot: allow it under System Settings → Privacy & Security → Microphone,
then restart that app. Without it, macOS hands the bot silence rather than an
error, so a stream that starts but stays silent usually means this permission
is missing.

## Similar projects

Streaming a local audio input into Discord through a bot is not a new idea.
These projects are worth a look, depending on what you need:

- [discord-audio-pipe](https://github.com/QiCuiHub/discord-audio-pipe): pipes any
  input (mic, stereo mix, virtual cable) to a bot, with a GUI and a ready-made
  Windows `.exe`. Pick it for a point-and-click setup on Windows.
- [discord-mic-bot](https://github.com/m13253/discord-mic-bot): stereo mic bot for
  karaoke or an instrument, with a loudness meter.
- [AudioWarp](https://github.com/cptpiepmatz/AudioWarp): Windows bot for an
  instrument or mixer input, built on discord.js.

This bot's angle is a USB amp on a Mac first: it is driven from Discord itself
(`/stream` joins your channel, and only you can run it), and it never streams
anything but the configured device, even when the amp is unplugged mid-stream.

## License

MIT
