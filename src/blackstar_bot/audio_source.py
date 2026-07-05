"""Custom discord.AudioSource that reads PCM from a USB audio device."""

from __future__ import annotations

import contextlib
import logging
import math
import queue
import threading
from typing import TYPE_CHECKING, Any

import discord
import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from blackstar_bot.device_finder import AudioDevice

# Discord expects 48kHz, 16-bit stereo, 20ms frames → 3840 bytes per read().
SAMPLE_RATE = 48000
CHANNELS = 2
FRAME_DURATION_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_DURATION_MS // 1000  # 960
BYTES_PER_FRAME = SAMPLES_PER_FRAME * CHANNELS * 2  # 3840

SILENCE = b"\x00" * BYTES_PER_FRAME


class BlackstarAudioSource(discord.AudioSource):  # type: ignore[misc]
    """Captures PCM audio from a Blackstar USB amp via sounddevice."""

    def __init__(self, device: AudioDevice, volume: float = 1.0) -> None:
        self._device = device
        self._buffer: queue.Queue[bytes] = queue.Queue(maxsize=50)
        self._stream: sd.RawInputStream | None = None
        self._lock = threading.Lock()
        self._volume = self._validate_volume(volume)

    @staticmethod
    def _validate_volume(volume: float) -> float:
        if not math.isfinite(volume) or volume < 0.0:
            msg = f"volume must be a finite non-negative number, got {volume}"
            raise ValueError(msg)
        return volume

    @property
    def volume(self) -> float:
        """Return the current playback volume multiplier."""
        with self._lock:
            return self._volume

    @property
    def device_name(self) -> str:
        """Return the capture device display name."""
        return self._device.name

    def set_volume(self, volume: float) -> None:
        """Set the playback volume multiplier."""
        with self._lock:
            self._volume = self._validate_volume(volume)

    def _audio_callback(
        self,
        indata: np.ndarray[Any, np.dtype[np.int16]],
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """Called by PortAudio when a new audio block is available."""
        data = bytes(indata)
        try:
            self._buffer.put_nowait(data)
        except queue.Full:
            # Drop oldest frame on overrun to keep latency low.
            logger.warning("Audio buffer overrun — dropping oldest frame to maintain low latency")
            with contextlib.suppress(queue.Empty):
                self._buffer.get_nowait()
            with contextlib.suppress(queue.Full):
                self._buffer.put_nowait(data)

    def start(self) -> None:
        """Open the PortAudio stream and begin capturing audio."""
        if self._device.default_samplerate != SAMPLE_RATE:
            msg = (
                f"Device '{self._device.name}' runs at "
                f"{self._device.default_samplerate} Hz, but 48000 Hz is required."
            )
            raise ValueError(msg)

        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=SAMPLES_PER_FRAME,
            device=self._device.index,
            callback=self._audio_callback,
        )
        self._stream.start()

    def read(self) -> bytes:
        """Return the next 3840-byte PCM frame, or silence on underrun."""
        try:
            data = self._buffer.get(timeout=0.05)
        except queue.Empty:
            return SILENCE

        vol = self.volume
        if vol != 1.0:
            samples = np.frombuffer(data, dtype=np.int16)
            samples = np.clip(samples * vol, -32768, 32767).astype(np.int16)
            return bytes(samples.tobytes())
        return data

    def is_opus(self) -> bool:
        """Return False — discord.py handles Opus encoding."""
        return False

    def cleanup(self) -> None:
        """Stop and close the PortAudio stream (idempotent, thread-safe)."""
        with self._lock:
            if self._stream is not None:
                with contextlib.suppress(Exception):
                    self._stream.stop()
                self._stream.close()
                self._stream = None
