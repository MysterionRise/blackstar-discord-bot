# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

### Added

- `INPUT_CHANNELS` chooses which device inputs are streamed: `1,2` (the
  default), a single input such as `1` sent to both sides as mono, or a pair
  such as `3,4`. Single-input devices (guitar-to-USB cables, one-input
  interfaces) were refused before, and a guitar in input 1 of a two-input
  interface was heard on the left only. The setup wizard asks which inputs to
  stream, `/status` shows them, and the FFmpeg backend logs that it ignores the
  setting
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
  permissions set to `0600` before the token is written. A replaced `.env` is
  kept as `.env.bak`, also `0600`, and `.gitignore` now covers every `.env.*`
  file except `.env.example`
- Experimental Dockerfile and Compose file for Linux hosts, passing `/dev/snd`
  into an unprivileged container. Docker Desktop on macOS cannot reach host USB
  audio, so Mac users should install natively
- Automatic stop: a stream ends 30 seconds after the user who started it leaves
  the voice channel, or after no human is left in it, with a short public
  notice. Rejoining within the grace period cancels it. If the bot itself is
  kicked or disconnected, the capture device is released straight away
- One stream per instance: `/stream` is refused while the amp is already
  streaming anywhere, including another server, or while another `/stream` is
  still connecting. `/stop`, `/status` and `/volume` act on the active stream
  from any server the bot is in

- `LOG_LEVEL` setting (`DEBUG`, `INFO`, `WARNING` or `ERROR`; default `INFO`,
  case-insensitive) controls log verbosity

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

- Release notes now come from this file: the release workflow publishes the
  `CHANGELOG.md` section for the pushed `vX.Y.Z` tag, and fails if the tag does
  not match the `pyproject.toml` version. It previously ran `cz changelog` with
  no Commitizen config, whose default tag format never matched the `v` tags.
  The package version is now read from `pyproject.toml` only
- Structured log fields are no longer dropped. Context passed to the logger
  (device, backend, volume, channel, attempt number and so on) was missing from
  every log line because the format had no place for it, so `DEBUG_CONFIG=true`
  printed `stream_config` with no values. Fields now follow the message as
  `key=value`, on stderr and in `LOG_FILE`
- Blocking PortAudio work no longer runs on the bot's event loop. Device
  re-enumeration, lookup and stream start in `/stream`, the device list in
  `/devices`, and capture teardown (which can wait seconds for the watchdog)
  now run in worker threads, so the gateway heartbeat and other commands keep
  responding. PortAudio re-enumeration, device queries and stream opening are
  serialized by one lock, so `/devices` can no longer query PortAudio while the
  watchdog thread is reinitializing it
- Capture latency is now bounded to roughly 40–100 ms. The capture buffer held
  up to 50 frames (1 s) and dropped only one frame per overrun, so a small
  clock drift between the amp and the voice player left audio sitting about
  1 s behind the guitar. It now holds at most 5 frames and trims back to 2 on
  overrun. Overrun warnings are rate-limited to one every 10 s, instead of up
  to 50 a second from the audio thread, and `read()` no longer blocks the
  voice player for up to 50 ms when the buffer is empty
- Require py-cord >= 2.8.0. Discord enforced the DAVE end-to-end-encryption
  protocol on 2 March 2026 and closes voice websockets from older clients with
  code 4017, so 2.7.x cannot join a voice channel at all
- Corrected the local `VoiceClient` protocol to mirror py-cord's real `play()`
  signature, so mypy checks calls against the actual API
- `/stream` and `/stop` now defer the interaction before connecting to voice,
  so Discord no longer reports "The application did not respond" while the
  voice handshake is in flight
- Audio device matching no longer settles for the first substring hit:
  - An exact name wins.
  - A query that matches several different inputs is refused, and the
    candidates are listed.
  - On Windows the WASAPI listing is preferred over the MME duplicate.
  - The stream identity check now requires the selected device's exact name,
    so a loose query such as `USB` cannot accept whichever USB input took the
    amp's index.
- The sounddevice backend asks PortAudio whether a device can capture 48 kHz
  16-bit stereo instead of trusting its default rate. Interfaces that default
  to 44.1 kHz now work, and mono inputs are refused up front with a clear reason
  rather than failing at stream open.
- `/devices` re-scans for hot-plugged devices first, unless a capture stream is
  open, and shows each device's host API
- A capture stream that opened but failed to start is now closed instead of
  leaked

### Changed

- **Breaking:** the project is renamed from `blackstar-discord-bot` to
  `discord-guitar-amp-bot`, because it streams any USB amp, modeller or audio
  interface, not only Blackstar amps. The package is now `guitar_amp_bot`, the
  commands are `guitar-amp-bot` and `guitar-amp-bot-setup`, the default log file
  is `guitar-amp-bot.log`, and `BlackstarAudioSource` is `DeviceAudioSource`.
  `blackstar-bot`, `blackstar-bot-sd` and `blackstar-bot-setup` remain as
  aliases. To migrate an existing checkout: `pip uninstall blackstar-discord-bot`
  then `pip install -e .`; `.env` needs no changes
- **Breaking:** `AUDIO_DEVICE` is required and has no default (it was
  `Blackstar`), and a blank value is rejected: a guessed or empty query could
  match the wrong input. The setup wizard always writes it, and no longer
  accepts a blank answer for the device
- README leads with what the bot is for and why a bot beats using the amp as a
  Discord microphone, lists verified and expected hardware, documents the macOS
  microphone permission, and credits similar projects
- README, `PLAN.md`, `AGENTS.md` and the `.claude/agents` prompts describe the
  current code. Changes:
  - a per-platform requirements table
  - a reference for every setting, including `VOLUME`
  - per-platform FFmpeg device naming
  - the full module map and device-safety design
  - the real `Settings` schema
- Command replies that expose local hardware or exception text are now
  ephemeral; only the stream start/stop notices remain visible to the channel
- `OWNER_ID` is optional again: unset, it resolves to the owner of the bot's
  own Discord application rather than allowing everyone. `DISCORD_TOKEN` is now
  the only required setting
- A missing `GUILD_ID` is logged as information rather than a warning, since
  global registration is the normal setup for a self-hosted instance
- **Breaking:** the legacy FFmpeg-only bot (`blackstar_bot.bot`, run as
  `python -m blackstar_bot.bot`) is removed. It had no connect retry or error
  handling and only `/stream` and `/stop`. `blackstar-bot` now starts the
  unified bot; set `AUDIO_BACKEND=ffmpeg` for FFmpeg capture.
  `blackstar-bot-sd` remains as an alias
- **Breaking:** `/stream` no longer accepts `device_name` or `backend`
  arguments — the input device and backend come from configuration only, so no
  Discord user can redirect the stream to another local input
