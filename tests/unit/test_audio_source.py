"""Tests for blackstar_bot.audio_source."""

import logging
import struct

import numpy as np
import pytest

from blackstar_bot.audio_source import BYTES_PER_FRAME, SILENCE, BlackstarAudioSource
from blackstar_bot.device_finder import AudioDevice


@pytest.fixture
def device_48k():
    return AudioDevice(
        index=5,
        name="Blackstar ID:Core V4",
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


def test_read_returns_correct_size(device_48k):
    """read() should return exactly BYTES_PER_FRAME bytes."""
    source = BlackstarAudioSource(device_48k)
    # Manually put data into the buffer
    frame = b"\x00" * BYTES_PER_FRAME
    source._buffer.put_nowait(frame)
    result = source.read()
    assert len(result) == BYTES_PER_FRAME


def test_read_returns_silence_on_underrun(device_48k):
    """read() should return silence bytes when the buffer is empty."""
    source = BlackstarAudioSource(device_48k)
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
    source = BlackstarAudioSource(device_48k, volume=0.5)
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
    source = BlackstarAudioSource(device_48k, volume=1.0)
    num_samples = BYTES_PER_FRAME // 2
    frame = struct.pack(f"<{num_samples}h", *([12345] * num_samples))
    source._buffer.put_nowait(frame)
    result = source.read()
    assert result == frame


def test_audio_callback_logs_on_overrun(device_48k, caplog):
    """_audio_callback should log a WARNING when the buffer is full."""
    source = BlackstarAudioSource(device_48k)
    # Fill the buffer to capacity (maxsize=50)
    frame = b"\x00" * BYTES_PER_FRAME
    for _ in range(50):
        source._buffer.put_nowait(frame)
    assert source._buffer.full()

    # Trigger callback with new data — should cause overrun
    indata = np.zeros((960, 2), dtype=np.int16)
    with caplog.at_level(logging.WARNING, logger="blackstar_bot.audio_source"):
        source._audio_callback(indata, 960, None, None)

    assert any("overrun" in record.message for record in caplog.records)


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
    source = BlackstarAudioSource(device_48k, volume=0.0)
    num_samples = BYTES_PER_FRAME // 2
    frame = struct.pack(f"<{num_samples}h", *([0x7FFF] * num_samples))
    source._buffer.put_nowait(frame)
    result = source.read()
    out_samples = np.frombuffer(result, dtype=np.int16)
    assert all(s == 0 for s in out_samples)


def test_volume_clipping(device_48k):
    """Volume > 1.0 with max samples should clip, not overflow."""
    source = BlackstarAudioSource(device_48k, volume=2.0)
    num_samples = BYTES_PER_FRAME // 2
    frame = struct.pack(f"<{num_samples}h", *([0x7FFF] * num_samples))
    source._buffer.put_nowait(frame)
    result = source.read()
    out_samples = np.frombuffer(result, dtype=np.int16)
    assert all(s == 32767 for s in out_samples)


def test_set_volume_updates_runtime_scaling(device_48k):
    """set_volume() should affect later reads."""
    source = BlackstarAudioSource(device_48k, volume=1.0)
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
    assert source.device_name == "Blackstar ID:Core V4"
