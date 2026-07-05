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
# Edit .env and add your DISCORD_TOKEN.
# AUDIO_BACKEND defaults to sounddevice; set it to ffmpeg only as a fallback.
```

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
- `/stream` — Join your voice channel and start streaming audio; accepts optional device/backend overrides
- `/stop` — Stop streaming and disconnect
- `/status` — Show whether the bot is streaming
- `/devices` — List detected audio input devices
- `/volume` — Show or change the sounddevice playback volume

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
  device_finder.py     # Audio device discovery
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
