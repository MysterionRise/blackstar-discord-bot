# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

### Added

- Project scaffold: source layout, CI, pre-commit hooks, agent prompts
- `pyproject.toml` with full tool configuration (ruff, mypy, pytest, bandit)
- GitHub Actions CI pipeline (lint, typecheck, test, security)
- GitHub issue and PR templates
- Claude Code agentic team configuration (orchestrator + 4 specialist agents)
- Runtime backend selection, device listing, status, and volume slash commands
- Safer stream startup cleanup, voice connect retry, and playback diagnostics
- Owner-only authorization: all slash commands require `OWNER_ID` and refuse
  everyone else with a private reply
- Optional `GUILD_ID` scoping so slash commands register in one server only
- Persistent audit log: refusals record the rejected user ID, written to stderr
  and a rotating file at `LOG_FILE` (default `blackstar-bot.log`)
- Self-hosting: anyone can run their own instance against their own amp. The
  bot authorizes the owner of its own Discord application when `OWNER_ID` is
  unset, logs an `invite_url=` line for adding itself to servers, and warns
  when a team-owned application widens that to every team member
- `blackstar-bot-setup`, an interactive wizard that creates `.env` — hidden
  token entry, audio device picked from the detected inputs, and file
  permissions set to `0600`
- Experimental Dockerfile and Compose file for Linux hosts, passing `/dev/snd`
  into an unprivileged container. Docker Desktop on macOS cannot reach host USB
  audio, so Mac users should install natively

### Security

- **Capture no longer falls through to another input device.** When the amp was
  unplugged mid-stream, PortAudio's cached device list and positional indices
  meant the stream could end up on whatever took the amp's index — typically the
  built-in microphone — and the bot kept broadcasting the room to the voice
  channel. The device name is now the identity and the index only a handle: the
  device list is re-enumerated before a stream opens, the live name at the
  opened index is verified, and any loss of the device mutes capture
  immediately. A watchdog then re-acquires the amp by name and resumes audio,
  giving up after 60 seconds and stopping the stream

### Fixed

- Require py-cord >= 2.8.0. Discord enforced the DAVE end-to-end-encryption
  protocol on 2 March 2026 and closes voice websockets from older clients with
  code 4017, so 2.7.x cannot join a voice channel at all
- Corrected the local `VoiceClient` protocol to mirror py-cord's real `play()`
  signature, so mypy checks calls against the actual API
- `/stream` and `/stop` now defer the interaction before connecting to voice,
  so Discord no longer reports "The application did not respond" while the
  voice handshake is in flight

### Changed

- Command replies that expose local hardware or exception text are now
  ephemeral; only the stream start/stop notices remain visible to the channel
- `OWNER_ID` is optional again: unset, it resolves to the owner of the bot's
  own Discord application rather than allowing everyone. `DISCORD_TOKEN` is now
  the only required setting
- A missing `GUILD_ID` is logged as information rather than a warning, since
  global registration is the normal setup for a self-hosted instance
- **Breaking:** `/stream` no longer accepts `device_name` or `backend`
  arguments — the input device and backend come from configuration only, so no
  Discord user can redirect the stream to another local input
