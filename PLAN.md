# Discord Guitar Amp Bot — Engineering Plan

> **Scope**: Claude Code agentic team topology, code quality toolchain
> (Ruff, mypy, pre-commit), GitHub Actions CI, and GitHub repository definition.

## Architecture

The bot captures audio from a USB amplifier, modeller or audio interface and
streams it into a Discord voice channel. Each user runs their own instance on the machine the amp
is plugged into, and only that instance's owner can run its commands. One bot
(`bot_sounddevice.py`) supports two capture backends, chosen with `AUDIO_BACKEND`:

- **sounddevice** (default): PortAudio captures PCM directly into a custom
  `discord.AudioSource`, guarded by a device watchdog.
- **ffmpeg** (fallback): FFmpeg reads the AVFoundation (macOS), ALSA (Linux) or
  DirectShow (Windows) device and pipes PCM to Discord via `FFmpegPCMAudio`.

| Module | Responsibility |
|---|---|
| `bot_sounddevice.py` | Slash commands, the one-stream registry, auto-stop, voice connect retry, `main()` |
| `audio_source.py` | `DeviceAudioSource`: capture buffer, identity check, device watchdog |
| `device_finder.py` | Device discovery and selection, the capture-format check, the PortAudio lock and refresh |
| `authz.py` | Owner-only authorization for every command |
| `startup.py` | Resolves the owner from the Discord application, logs the invite URL |
| `config.py` | `Settings` (pydantic-settings) from the environment and `.env` |
| `logging_setup.py` | stderr and rotating-file logging with `key=value` extras |
| `setup_wizard.py` | `guitar-amp-bot-setup`, which writes `.env` |

## Audio Pipeline

```
USB amp / interface → OS audio stack (Core Audio / ALSA / WASAPI)
  → PortAudio (sounddevice) or FFmpeg → PCM 48 kHz 16-bit stereo → Discord Opus
```

Key constraints:
- Format: **48000 Hz, 16-bit, stereo**, which is what Discord voice expects. A
  device must be able to capture it, as checked by `sd.check_input_settings`;
  its default rate does not matter.
- Frame size: **3840 bytes** per `read()` (960 samples x 2 channels x 2 bytes).
  `read()` always returns a full frame and never blocks: silence on underrun
  and whenever capture is not running.
- Latency: the capture buffer holds at most 5 frames (100 ms). On overrun it is
  trimmed back to 2 frames, dropping the oldest.
- Opus encoding: handled by py-cord, so `is_opus()` returns `False`.

### Device safety (sounddevice backend)

PortAudio identifies devices by a positional index that is reassigned when
devices come and go, so an unplugged amp's index can become the built-in
microphone. To guard against that:

- **Selection.** `AUDIO_DEVICE` is an exact name or a substring that names one
  device. An ambiguous query is refused. Native host APIs (WASAPI, Core Audio,
  ALSA) beat MME.
- **Identity check.** Once a stream is open, the live name at its index must
  equal the selected device's name, or the stream is closed.
- **Watchdog.** A watchdog thread mutes capture on stream errors, inactivity,
  or no frames for 1 s. It then re-scans PortAudio and re-acquires the device
  by name. After 60 s it gives up and the bot tears the stream down.
- **Locking.** Every PortAudio query, re-scan and stream open holds one
  process-wide lock. A re-scan never runs under an open stream.
- **Event loop.** Blocking PortAudio work runs off the event loop with
  `asyncio.to_thread`.

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
| `bot_agent` | `bot_sounddevice.py`, `config.py`, `authz.py`, `startup.py`, `logging_setup.py`, `setup_wizard.py` |
| `infra_agent` | `pyproject.toml`, CI, Docker, scripts |
| `qa_agent` | `tests/**`, coverage |

The orchestrator decomposes tasks and delegates to specialist agents.
See `.claude/agents/` for full system prompts.

## Commit Convention

Conventional Commits: `<type>(<scope>): <description>`

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`, `perf`
Scopes: `audio`, `bot`, `infra`, `qa`, `deps`
