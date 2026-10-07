# Audio Agent

You own the audio capture pipeline for the Discord guitar amp bot.

## Your files (only modify these unless explicitly instructed otherwise)
- `src/guitar_amp_bot/audio_source.py`
- `src/guitar_amp_bot/device_finder.py`
- `tests/unit/test_audio_source.py`
- `tests/unit/test_device_finder.py`

## Constraints
- Always capture **48000 Hz, 16-bit, stereo**, which is Discord's voice format.
  Check that a device supports it with `capture_problem()`, which wraps
  `sd.check_input_settings`. Never compare `default_samplerate`.
- `read()` must always return **exactly 3840 bytes** and never block. It must
  never return `b""`, which would end playback. Return silence
  (`b"\x00" * 3840`) on underrun and whenever capture is not running.
- `is_opus()` must return `False` — py-cord handles Opus encoding.
- Never emit audio that cannot be attributed to the selected device. Once a
  stream is open, the live name at its index must equal the selected device's
  name. On loss, mute first, then re-acquire by name.
- Hold `portaudio_lock()` for every PortAudio query and stream open. Never
  re-scan (`refresh_devices`) while a stream is open. Open and close streams
  only through `_open_verified_stream` and `_force_close`, so the open-stream
  count stays right.
- All public functions and classes require full type annotations.
- Run `ruff check src/guitar_amp_bot/audio_source.py src/guitar_amp_bot/device_finder.py`
  after every edit. Fix all issues before reporting back.

## Key invariants to test
- Buffer underrun produces silence, not `b""`.
- Buffer overrun trims to the target depth, dropping the oldest frames.
- `cleanup()` stops and closes the PortAudio stream, and is idempotent and safe
  to call from the watchdog thread.
- Device selection: an exact name beats a substring, a query matching
  several different devices raises `AmbiguousDeviceError`, and native host
  APIs rank above MME.
- A device that cannot capture 48 kHz stereo raises a `ValueError` that says why.
- Tests wait on `threading.Event`s, never `time.sleep` polling.
