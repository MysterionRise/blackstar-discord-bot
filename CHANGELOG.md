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

### Fixed

- `/stream` and `/stop` now defer the interaction before connecting to voice,
  so Discord no longer reports "The application did not respond" while the
  voice handshake is in flight

### Changed

- Command replies that expose local hardware or exception text are now
  ephemeral; only the stream start/stop notices remain visible to the channel
- **Breaking:** `OWNER_ID` is now required; the bot fails to start without it
- **Breaking:** `/stream` no longer accepts `device_name` or `backend`
  arguments — the input device and backend come from configuration only, so no
  Discord user can redirect the stream to another local input
