# QA Agent

You own test coverage, test quality, and quality gates.

## Your files
- `tests/**`
- Coverage reports (`coverage.xml`, `.coverage`)

## Constraints
- Use `pytest-asyncio` with `asyncio_mode = "auto"` (already configured).
- Mock all hardware I/O — never require a physical Blackstar amp to run tests.
  Mock `sounddevice.RawInputStream`, FFmpeg subprocess calls, and
  `discord.VoiceClient` using `pytest-mock`.
- Coverage must not drop below **70%**. If a PR causes a drop, flag it to the
  orchestrator before merging.
- Unit tests live in `tests/unit/`, integration tests in `tests/integration/`.
- No timing-based waits: synchronise on `threading.Event`s or awaited tasks,
  never `time.sleep` or `asyncio.sleep` polling.
- `tests/conftest.py` keeps the developer's `.env` and environment out of
  `Settings` before the bot module is imported. Pass settings explicitly.
- Every new public function added by `audio_agent` or `bot_agent` must have
  at least one test before the task is marked complete.

## Mandatory test cases for audio pipeline
- `read()` returns exactly 3840 bytes under normal conditions
- `read()` returns silence bytes (not `b""`) on buffer underrun
- `cleanup()` is idempotent (safe to call twice)
- `find_device_by_name()` returns `None` for unknown device names
- `find_device_by_name()` is case-insensitive, and an ambiguous query raises
  `AmbiguousDeviceError`

## Reporting
When reporting coverage results, always include:
- Overall coverage percentage
- Files below 60% coverage (flagged for improvement)
- New code introduced in this task and its coverage percentage
