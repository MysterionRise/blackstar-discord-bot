# Blackstar Discord Bot — Engineering Plan

> **Scope**: Claude Code agentic team topology, code quality toolchain
> (Ruff, mypy, pre-commit), GitHub Actions CI, and GitHub repository definition.

## Architecture

The bot captures audio from a Blackstar USB amplifier and streams it into a
Discord voice channel. Two approaches are supported:

- **Approach A** (`bot_sounddevice.py`): Uses `sounddevice` (PortAudio) to
  capture PCM audio directly, wrapped in a custom `discord.AudioSource`.
- **Approach B** (`bot.py`): Uses FFmpeg to read from the ALSA/Core Audio
  device and pipes PCM to Discord via `FFmpegPCMAudio`.

## Audio Pipeline

```
Blackstar USB Amp → macOS Core Audio → sounddevice/FFmpeg → PCM 48kHz 16-bit stereo → Discord Opus
```

Key constraints:
- Sample rate: **48000 Hz** (Blackstar native + Discord requirement)
- Frame size: **3840 bytes** per `read()` (960 samples x 2 channels x 2 bytes)
- Buffer underrun: return silence (`b"\x00" * 3840`), never empty bytes
- Opus encoding: handled by discord.py, `is_opus()` returns `False`

## Quality Gates

| Gate | Tool | Runs when |
|---|---|---|
| Formatting | `ruff format` | pre-commit, CI |
| Linting | `ruff check` | pre-commit, CI |
| Type checking | `mypy --strict` | pre-commit, CI |
| Security scan | `bandit` | pre-commit, CI |
| Secret detection | `gitleaks` | pre-commit, CI |
| Tests | `pytest` | CI |
| Coverage (70%) | `pytest-cov` | CI |
| Commit format | `commitizen` | pre-commit |

## Claude Code Agentic Team

| Agent | Owns |
|---|---|
| `audio_agent` | `audio_source.py`, `device_finder.py` |
| `bot_agent` | `bot.py`, `bot_sounddevice.py`, `config.py` |
| `infra_agent` | `pyproject.toml`, CI, scripts |
| `qa_agent` | `tests/**`, coverage |

The orchestrator decomposes tasks and delegates to specialist agents.
See `.claude/agents/` for full system prompts.

## Commit Convention

Conventional Commits: `<type>(<scope>): <description>`

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`, `perf`
Scopes: `audio`, `bot`, `infra`, `qa`, `deps`
