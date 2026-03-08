# Blackstar Discord Bot

Python bot that streams guitar audio from a Blackstar USB amp into a Discord voice channel.

## Features

- Stream live guitar audio from a Blackstar amplifier into Discord voice chat
- Two audio approaches: FFmpeg-based (`bot.py`) and sounddevice-based (`bot_sounddevice.py`)
- Automatic USB audio device discovery
- Configurable volume control
- Slash commands (`/stream`, `/stop`)

## Requirements

- Python 3.12+
- macOS (for USB audio capture from Blackstar amp)
- FFmpeg (for Approach B)
- PortAudio (for Approach A / sounddevice)
- A Blackstar amplifier with USB audio output

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
# Edit .env and add your DISCORD_TOKEN
```

## Usage

```bash
# Check that your Blackstar amp is detected
python scripts/list_devices.py

# Run the bot (Approach B — FFmpeg)
python -m blackstar_bot.bot

# Or run the bot (Approach A — sounddevice)
python -m blackstar_bot.bot_sounddevice
```

In Discord, use:
- `/stream` — Join your voice channel and start streaming audio
- `/stop` — Stop streaming and disconnect

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

## License

MIT
