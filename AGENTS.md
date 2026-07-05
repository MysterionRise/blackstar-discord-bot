# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.12 Discord voice bot packaged from `src/blackstar_bot/`.
Core modules live there: `bot.py` is the FFmpeg-based bot, `bot_sounddevice.py`
is the sounddevice alternative, `audio_source.py` handles live capture,
`device_finder.py` discovers USB audio devices, and `config.py` loads settings.
Tests are under `tests/`, split into `tests/unit/` for mocked component tests and
`tests/integration/` for higher-level bot command behavior. Utility scripts live
in `scripts/`, including `scripts/list_devices.py` for local audio-device checks.

## Build, Test, and Development Commands

- `pip install -e ".[dev]"`: install the package and development tooling.
- `python -m blackstar_bot.bot`: run the FFmpeg bot entry point.
- `python -m blackstar_bot.bot_sounddevice`: run the sounddevice bot entry point.
- `python scripts/list_devices.py`: list available audio input devices.
- `pytest`: run the test suite with coverage reporting.
- `ruff check src/ tests/`: lint Python code.
- `ruff format --check src/ tests/`: verify formatting.
- `mypy src/`: run strict type checking.
- `pre-commit run --all-files`: run the full local quality gate.

## Coding Style & Naming Conventions

Use Ruff formatting with 100-character lines, spaces for indentation, and double
quotes. Keep imports sorted by Ruff/isort, with `blackstar_bot` treated as first
party. Production code should be fully typed; mypy runs in strict mode for `src`.
Use `snake_case` for modules, functions, and variables, and `PascalCase` for
classes. Avoid bare `print()` in source code; use logging or Discord responses as
appropriate.

## Testing Guidelines

Pytest is configured in `pyproject.toml` with `asyncio_mode = "auto"` and a
minimum coverage threshold of 70% for `src/blackstar_bot`. Name tests as
`test_*.py` and keep hardware, Discord, and audio APIs mocked unless a manual
hardware check is explicitly required. Add or update unit tests for behavior in
individual modules and integration tests for command-level flows.

## Commit & Pull Request Guidelines

Commit messages are checked by Commitizen, so prefer conventional forms such as
`fix: handle missing input device` or `feat: add stream volume option`. Existing
history also contains Dependabot-style `Bump ...` commits. Pull requests should
include a short summary, change type, passing `pre-commit run --all-files`, type
annotations for new code, relevant `CHANGELOG.md` updates, and notes on whether
the change was tested with a physical Blackstar amp.

## Security & Configuration Tips

Copy `.env.example` to `.env` for local configuration and never commit tokens or
secrets. Gitleaks and Bandit run in pre-commit/CI; treat failures as blockers.
