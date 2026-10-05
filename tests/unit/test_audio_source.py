"""Tests for blackstar_bot.audio_source."""

import logging
import struct
import time

import numpy as np
import pytest

from blackstar_bot import audio_source
from blackstar_bot.audio_source import (
    BYTES_PER_FRAME,
    MAX_BUFFER_FRAMES,
    OVERRUN_LOG_INTERVAL_SECONDS,
    SILENCE,
    STARVATION_SECONDS,
    TARGET_BUFFER_FRAMES,
    BlackstarAudioSource,
    DeviceIdentityError,
)
from blackstar_bot.device_finder import AudioDevice

BLACKSTAR_NAME = "Blackstar ID:Core V4"
OTHER_DEVICE_NAME = "MacBook Pro Microphone"


@pytest.fixture
def device_48k():
    return AudioDevice(
        index=5,
        name=BLACKSTAR_NAME,
        max_input_channels=2,
        default_samplerate=48000.0,
    )


@pytest.fixture
def device_44k():
    return AudioDevice(
        index=3,
        name="Bad Device",
        max_input_channels=2,
        default_samplerate=44100.0,
    )


class FakeStream:
    """Stand-in for sd.RawInputStream that records its lifecycle."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.active = True
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        self.active = False

    def close(self):
        self.closed = True


class FakeStatus:
    """Stand-in for sd.CallbackFlags."""

    def __init__(self, *, input_overflow=False, input_underflow=False):
        self.input_overflow = input_overflow
        self.input_underflow = input_underflow

    def __bool__(self):
        return self.input_overflow or self.input_underflow


@pytest.fixture
def fake_streams(monkeypatch):
    """Replace sounddevice so streams can be opened without hardware."""
    created = []

    class _FakeSD:
        @staticmethod
        def RawInputStream(**kwargs):  # noqa: N802
            stream = FakeStream(**kwargs)
            created.append(stream)
            return stream

    monkeypatch.setattr(audio_source, "sd", _FakeSD)
    return created


def _reports(monkeypatch, name):
    """Make the live device lookup report *name* at every index."""
    monkeypatch.setattr(audio_source, "live_device_name", lambda _index: name)


def _running(source):
    """Put a source in the running state without opening real hardware."""
    source._state = "running"
    return source


def test_read_returns_correct_size(device_48k):
    """read() should return exactly BYTES_PER_FRAME bytes."""
    source = _running(BlackstarAudioSource(device_48k))
    # Manually put data into the buffer
    frame = b"\x00" * BYTES_PER_FRAME
    source._buffer.put_nowait(frame)
    result = source.read()
    assert len(result) == BYTES_PER_FRAME


def test_read_returns_silence_on_underrun(device_48k):
    """read() should return silence bytes when the buffer is empty."""
    source = _running(BlackstarAudioSource(device_48k))
    result = source.read()
    assert result == SILENCE
    assert len(result) == BYTES_PER_FRAME


def test_is_opus_returns_false(device_48k):
    """is_opus() must always return False."""
    source = BlackstarAudioSource(device_48k)
    assert source.is_opus() is False


def test_cleanup_is_idempotent(device_48k):
    """cleanup() should be safe to call multiple times."""
    source = BlackstarAudioSource(device_48k)
    source.cleanup()
    source.cleanup()  # Should not raise


def test_start_rejects_wrong_sample_rate(device_44k):
    """start() should raise ValueError for non-48kHz devices."""
    source = BlackstarAudioSource(device_44k)
    with pytest.raises(ValueError, match="48000"):
        source.start()


def test_read_applies_volume_scaling(device_48k):
    """read() at volume=0.5 should halve sample amplitudes."""
    source = _running(BlackstarAudioSource(device_48k, volume=0.5))
    # Create a frame of 0x7FFF (32767) samples — max positive int16
    num_samples = BYTES_PER_FRAME // 2  # 2 bytes per int16 sample
    frame = struct.pack(f"<{num_samples}h", *([0x7FFF] * num_samples))
    source._buffer.put_nowait(frame)
    result = source.read()
    # Parse output samples
    out_samples = np.frombuffer(result, dtype=np.int16)
    # Each sample should be approximately 16383 (32767 * 0.5)
    assert all(abs(int(s) - 16383) <= 1 for s in out_samples)


def test_read_skips_scaling_at_unity_volume(device_48k):
    """read() at volume=1.0 should return bytes identical to input."""
    source = _running(BlackstarAudioSource(device_48k, volume=1.0))
    num_samples = BYTES_PER_FRAME // 2
    frame = struct.pack(f"<{num_samples}h", *([12345] * num_samples))
    source._buffer.put_nowait(frame)
    result = source.read()
    assert result == frame


def test_audio_callback_logs_on_overrun(device_48k, caplog):
    """_audio_callback should log a WARNING when the buffer is full."""
    source = BlackstarAudioSource(device_48k)
    frame = b"\x00" * BYTES_PER_FRAME
    for _ in range(MAX_BUFFER_FRAMES):
        source._buffer.put_nowait(frame)
    assert source._buffer.full()

    # Trigger callback with new data — should cause overrun
    indata = np.zeros((960, 2), dtype=np.int16)
    with caplog.at_level(logging.WARNING, logger="blackstar_bot.audio_source"):
        source._audio_callback(indata, 960, None, None)

    assert any("overrun" in record.message for record in caplog.records)


def _marker_frame(value):
    return bytes([value]) * BYTES_PER_FRAME


def _callback_with(source, value):
    """Feed one 20 ms block whose every byte is *value* through the callback."""
    indata = np.frombuffer(_marker_frame(value), dtype=np.int16).reshape(960, 2)
    source._audio_callback(indata, 960, None, None)


def test_overrun_trims_to_target_keeping_newest_frames(device_48k):
    """An overrun drops the oldest audio, not the newest, down to the target depth."""
    source = BlackstarAudioSource(device_48k)
    for value in range(1, MAX_BUFFER_FRAMES + 1):
        source._buffer.put_nowait(_marker_frame(value))

    _callback_with(source, 99)

    assert source._buffer.qsize() == TARGET_BUFFER_FRAMES
    remaining = [source._buffer.get_nowait() for _ in range(TARGET_BUFFER_FRAMES)]
    newest_kept = range(MAX_BUFFER_FRAMES - TARGET_BUFFER_FRAMES + 2, MAX_BUFFER_FRAMES + 1)
    assert remaining == [_marker_frame(v) for v in newest_kept] + [_marker_frame(99)]


def test_latency_stays_bounded_without_reads(device_48k):
    """A capture clock running ahead of playback can never queue more than the ceiling."""
    source = BlackstarAudioSource(device_48k)

    for _ in range(200):
        _callback_with(source, 7)

    assert source._buffer.qsize() <= MAX_BUFFER_FRAMES


def test_overrun_logging_is_rate_limited(device_48k, caplog, monkeypatch):
    """Overruns on the real-time thread log once per interval, not once per frame."""
    clock = [1000.0]
    monkeypatch.setattr(audio_source.time, "monotonic", lambda: clock[0])
    source = BlackstarAudioSource(device_48k)

    with caplog.at_level(logging.WARNING, logger="blackstar_bot.audio_source"):
        for _ in range(100):
            _callback_with(source, 1)
        first_burst = [r for r in caplog.records if "buffer_overrun" in r.message]

        clock[0] += OVERRUN_LOG_INTERVAL_SECONDS
        # Enough blocks to overflow again from any depth the burst left behind.
        for _ in range(MAX_BUFFER_FRAMES + 1):
            _callback_with(source, 1)

    overrun_logs = [r for r in caplog.records if "buffer_overrun" in r.message]
    assert len(first_burst) == 1
    assert len(overrun_logs) == 2
    # The second report covers every frame dropped since the first one.
    assert "dropped=" in overrun_logs[1].getMessage()
    assert "dropped=0 " not in overrun_logs[1].getMessage()


def test_read_does_not_block_on_empty_buffer(device_48k):
    """read() must never wait: a blocking get stalls the voice player's 20 ms loop."""
    source = BlackstarAudioSource(device_48k)
    source._state = "running"

    real_get = source._buffer.get

    def _non_blocking_only(block=True, timeout=None):
        assert not block, "read() must not use a blocking get"
        return real_get(block, timeout)

    source._buffer.get = _non_blocking_only

    assert source.read() == SILENCE


def test_volume_rejects_negative(device_48k):
    """Negative volume should raise ValueError."""
    with pytest.raises(ValueError, match="non-negative"):
        BlackstarAudioSource(device_48k, volume=-1.0)


def test_volume_rejects_nan(device_48k):
    """NaN volume should raise ValueError."""
    with pytest.raises(ValueError, match="finite"):
        BlackstarAudioSource(device_48k, volume=float("nan"))


def test_volume_zero_produces_silence(device_48k):
    """Volume 0.0 should produce all-zero output."""
    source = _running(BlackstarAudioSource(device_48k, volume=0.0))
    num_samples = BYTES_PER_FRAME // 2
    frame = struct.pack(f"<{num_samples}h", *([0x7FFF] * num_samples))
    source._buffer.put_nowait(frame)
    result = source.read()
    out_samples = np.frombuffer(result, dtype=np.int16)
    assert all(s == 0 for s in out_samples)


def test_volume_clipping(device_48k):
    """Volume > 1.0 with max samples should clip, not overflow."""
    source = _running(BlackstarAudioSource(device_48k, volume=2.0))
    num_samples = BYTES_PER_FRAME // 2
    frame = struct.pack(f"<{num_samples}h", *([0x7FFF] * num_samples))
    source._buffer.put_nowait(frame)
    result = source.read()
    out_samples = np.frombuffer(result, dtype=np.int16)
    assert all(s == 32767 for s in out_samples)


def test_set_volume_updates_runtime_scaling(device_48k):
    """set_volume() should affect later reads."""
    source = _running(BlackstarAudioSource(device_48k, volume=1.0))
    source.set_volume(0.25)
    assert source.volume == 0.25

    num_samples = BYTES_PER_FRAME // 2
    frame = struct.pack(f"<{num_samples}h", *([12000] * num_samples))
    source._buffer.put_nowait(frame)
    result = source.read()
    out_samples = np.frombuffer(result, dtype=np.int16)
    assert all(abs(int(s) - 3000) <= 1 for s in out_samples)


def test_device_name_exposes_selected_device(device_48k):
    """device_name should expose the capture device display name."""
    source = BlackstarAudioSource(device_48k)
    assert source.device_name == BLACKSTAR_NAME


# --- Device identity and loss -------------------------------------------------
#
# Losing the amp must never fall through to whatever input now holds its
# index: the device list PortAudio caches can be stale, and indices shift.


def test_start_opens_verified_matching_device(device_48k, fake_streams, monkeypatch):
    """A device whose live name still matches is streamed normally."""
    _reports(monkeypatch, BLACKSTAR_NAME)
    source = BlackstarAudioSource(device_48k, device_query="Blackstar")
    source.start()
    try:
        assert source.state == "running"
        assert fake_streams[0].kwargs["device"] == 5
        assert fake_streams[0].started is True
    finally:
        source.cleanup()


def test_start_refuses_when_index_holds_another_device(device_48k, fake_streams, monkeypatch):
    """A stale index pointing at a microphone must never be streamed."""
    _reports(monkeypatch, OTHER_DEVICE_NAME)
    source = BlackstarAudioSource(device_48k, device_query="Blackstar")

    with pytest.raises(DeviceIdentityError, match="Microphone"):
        source.start()

    assert fake_streams[0].closed is True
    assert source.state == "stopped"
    assert source.read() == SILENCE


def test_start_refuses_when_live_name_is_unknown(device_48k, fake_streams, monkeypatch):
    """An unreadable device name is treated as a mismatch, not as a pass."""
    _reports(monkeypatch, None)
    source = BlackstarAudioSource(device_48k, device_query="Blackstar")

    with pytest.raises(DeviceIdentityError):
        source.start()

    assert fake_streams[0].closed is True
    assert source.read() == SILENCE


def test_read_returns_silence_while_reacquiring(device_48k):
    """Capture is muted the moment the device identity is in doubt."""
    source = _running(BlackstarAudioSource(device_48k))
    source._buffer.put_nowait(b"\x11" * BYTES_PER_FRAME)

    source._signal_loss("unplugged")

    assert source.state == "reacquiring"
    assert source.read() == SILENCE


def test_loss_drains_frames_captured_before_the_gap(device_48k):
    """Queued frames may be from the replacement device, so they are dropped."""
    source = _running(BlackstarAudioSource(device_48k))
    source._buffer.put_nowait(b"\x11" * BYTES_PER_FRAME)

    source._signal_loss("unplugged")
    assert source._buffer.empty()

    # Even once running again, the pre-loss frame must not surface.
    _running(source)
    assert source.read() == SILENCE


def test_inactive_stream_triggers_loss(device_48k):
    """A stream PortAudio aborted means the device is gone."""
    source = _running(BlackstarAudioSource(device_48k))
    stream = FakeStream()
    stream.active = False

    source._check_running_stream(stream, time.monotonic())

    assert source.state == "reacquiring"


def test_frame_starvation_triggers_loss(device_48k):
    """A silent-but-open stream is treated as a loss rather than as quiet."""
    source = _running(BlackstarAudioSource(device_48k))

    source._check_running_stream(FakeStream(), time.monotonic() - STARVATION_SECONDS - 0.5)

    assert source.state == "reacquiring"


def test_callback_error_status_triggers_loss(device_48k):
    """A non-overflow callback status means capture can no longer be trusted."""
    source = _running(BlackstarAudioSource(device_48k))
    indata = np.zeros((960, 2), dtype=np.int16)

    source._audio_callback(indata, 960, None, FakeStatus(input_underflow=True))

    assert source.state == "reacquiring"
    assert source._buffer.empty()


def test_callback_overflow_status_keeps_streaming(device_48k):
    """An overflow is normal under load and must not mute the stream."""
    source = _running(BlackstarAudioSource(device_48k))
    indata = np.zeros((960, 2), dtype=np.int16)

    source._audio_callback(indata, 960, None, FakeStatus(input_overflow=True))

    assert source.state == "running"


def test_reacquire_resumes_on_matching_device(device_48k, fake_streams, monkeypatch):
    """Audio resumes by name once the amp is back."""
    monkeypatch.setattr(audio_source, "refresh_devices", lambda: None)
    monkeypatch.setattr(audio_source, "find_device_by_name", lambda _query: device_48k)
    _reports(monkeypatch, BLACKSTAR_NAME)
    source = BlackstarAudioSource(device_48k, device_query="Blackstar")
    source._state = "reacquiring"

    assert source._try_reacquire() is True
    assert source.state == "running"
    source.cleanup()


def test_reacquire_refuses_a_different_device(device_48k, fake_streams, monkeypatch):
    """The whole point: re-acquisition never settles for another input."""
    monkeypatch.setattr(audio_source, "refresh_devices", lambda: None)
    monkeypatch.setattr(audio_source, "find_device_by_name", lambda _query: device_48k)
    _reports(monkeypatch, OTHER_DEVICE_NAME)
    source = BlackstarAudioSource(device_48k, device_query="Blackstar")
    source._state = "reacquiring"

    assert source._try_reacquire() is False
    assert source.state == "reacquiring"
    assert source.read() == SILENCE
    assert fake_streams[0].closed is True


def test_reacquire_waits_while_device_is_absent(device_48k, monkeypatch):
    """With no matching device, stay muted rather than opening anything."""
    monkeypatch.setattr(audio_source, "refresh_devices", lambda: None)
    monkeypatch.setattr(audio_source, "find_device_by_name", lambda _query: None)
    source = BlackstarAudioSource(device_48k, device_query="Blackstar")
    source._state = "reacquiring"

    assert source._try_reacquire() is False
    assert source.state == "reacquiring"


def test_reacquire_rejects_wrong_sample_rate(device_48k, device_44k, monkeypatch):
    """A match at the wrong rate is refused, as it is at start."""
    monkeypatch.setattr(audio_source, "refresh_devices", lambda: None)
    monkeypatch.setattr(audio_source, "find_device_by_name", lambda _query: device_44k)
    source = BlackstarAudioSource(device_48k, device_query="Blackstar")
    source._state = "reacquiring"

    assert source._try_reacquire() is False


def test_give_up_notifies_once_and_stops(device_48k):
    """Giving up stops capture and notifies the bot layer a single time."""
    calls = []
    source = BlackstarAudioSource(device_48k, on_unavailable=lambda: calls.append(1))
    source._state = "reacquiring"

    source._give_up()
    source._give_up()

    assert calls == [1]
    assert source.state == "stopped"
    assert source.read() == SILENCE


def test_give_up_survives_a_failing_callback(device_48k):
    """A broken callback must not take the watchdog thread down with it."""

    def _boom():
        raise RuntimeError("boom")

    source = BlackstarAudioSource(device_48k, on_unavailable=_boom)
    source._state = "reacquiring"

    source._give_up()

    assert source.state == "stopped"


def _wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_watchdog_resumes_audio_once_the_device_returns(device_48k, fake_streams, monkeypatch):
    """End to end: a loss mutes capture, and the watchdog brings it back."""
    monkeypatch.setattr(audio_source, "WATCHDOG_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(audio_source, "RETRY_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(audio_source, "refresh_devices", lambda: None)
    monkeypatch.setattr(audio_source, "find_device_by_name", lambda _query: device_48k)
    _reports(monkeypatch, BLACKSTAR_NAME)

    source = BlackstarAudioSource(device_48k, device_query="Blackstar")
    source.start()
    try:
        source._signal_loss("unplugged")
        assert source.read() == SILENCE
        assert _wait_until(lambda: source.state == "running"), "watchdog never re-acquired"
    finally:
        source.cleanup()


def test_watchdog_gives_up_when_the_device_stays_gone(device_48k, fake_streams, monkeypatch):
    """After the timeout the bot layer is told, and capture stays muted."""
    monkeypatch.setattr(audio_source, "WATCHDOG_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(audio_source, "RETRY_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(audio_source, "REACQUIRE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(audio_source, "refresh_devices", lambda: None)
    monkeypatch.setattr(audio_source, "find_device_by_name", lambda _query: None)
    _reports(monkeypatch, BLACKSTAR_NAME)

    calls = []
    source = BlackstarAudioSource(
        device_48k, device_query="Blackstar", on_unavailable=lambda: calls.append(1)
    )
    source.start()
    try:
        source._signal_loss("unplugged")
        assert _wait_until(lambda: bool(calls)), "watchdog never gave up"
        assert source.state == "stopped"
        assert source.read() == SILENCE
    finally:
        source.cleanup()


def test_cleanup_closes_the_open_stream(device_48k, fake_streams, monkeypatch):
    """cleanup() releases the device so PortAudio can be reinitialized."""
    _reports(monkeypatch, BLACKSTAR_NAME)
    source = BlackstarAudioSource(device_48k, device_query="Blackstar")
    source.start()

    source.cleanup()

    assert fake_streams[0].closed is True
    assert source.state == "stopped"
    assert source.read() == SILENCE
