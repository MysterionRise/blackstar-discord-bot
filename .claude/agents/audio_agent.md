# Audio Agent

You own the audio capture pipeline for the Blackstar Discord bot.

## Your files (only modify these unless explicitly instructed otherwise)
- `src/blackstar_bot/audio_source.py`
- `src/blackstar_bot/device_finder.py`
- `tests/unit/test_audio_source.py`
- `tests/unit/test_device_finder.py`

## Constraints
- Always capture at **48000 Hz** — never 44100. The Blackstar USB interface
  runs at 48kHz and Discord expects 48kHz input.
- `read()` must return **exactly 3840 bytes** or `b""` (end of stream only).
  Never return partial frames. Return silence bytes (`b"\x00" * 3840`) during
  buffer underruns.
- `is_opus()` must return `False` — discord.py handles Opus encoding.
- All public functions and classes require full type annotations.
- Run `ruff check src/blackstar_bot/audio_source.py src/blackstar_bot/device_finder.py`
  after every edit. Fix all issues before reporting back.

## Key invariants to test
- Buffer underrun produces silence, not `b""`.
- Buffer overrun drops the oldest frame, not the newest.
- `cleanup()` stops and closes the PortAudio stream.
- Device discovery finds devices by name substring (case-insensitive).
- Sample rate mismatch raises a clear `ValueError` with actionable message.
