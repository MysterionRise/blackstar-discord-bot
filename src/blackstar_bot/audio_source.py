"""Custom discord.AudioSource that reads PCM from a USB audio device."""

from __future__ import annotations

import contextlib
import logging
import math
import queue
import threading
import time
from typing import TYPE_CHECKING, Any, Literal, cast

import discord
import numpy as np
import sounddevice as sd

from blackstar_bot.device_finder import find_device_by_name, live_device_name, refresh_devices

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from blackstar_bot.device_finder import AudioDevice

# Discord expects 48kHz, 16-bit stereo, 20ms frames → 3840 bytes per read().
SAMPLE_RATE = 48000
CHANNELS = 2
FRAME_DURATION_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_DURATION_MS // 1000  # 960
BYTES_PER_FRAME = SAMPLES_PER_FRAME * CHANNELS * 2  # 3840

SILENCE = b"\x00" * BYTES_PER_FRAME

WATCHDOG_INTERVAL_SECONDS = 0.5
STARVATION_SECONDS = 1.0
RETRY_BACKOFF_SECONDS = 2.0
REACQUIRE_TIMEOUT_SECONDS = 60.0
WATCHDOG_JOIN_TIMEOUT_SECONDS = 5.0

CaptureState = Literal["running", "reacquiring", "stopped"]


class DeviceIdentityError(RuntimeError):
    """Raised when an opened stream is not the configured capture device."""


class BlackstarAudioSource(discord.AudioSource):  # type: ignore[misc, unused-ignore]
    """Captures PCM audio from a Blackstar USB amp via sounddevice.

    Only audio positively attributed to the configured device is ever emitted.
    When the device disappears, capture is torn down and ``read`` returns
    silence until a device whose name still matches has been reopened — losing
    the amp must never fall through to whatever input replaced it.
    """

    def __init__(
        self,
        device: AudioDevice,
        volume: float = 1.0,
        *,
        device_query: str | None = None,
        on_unavailable: Callable[[], None] | None = None,
    ) -> None:
        self._device = device
        # Re-acquisition matches on the name, never the index: the index of a
        # vanished device gets reassigned to an unrelated input.
        self._device_query = device.name if device_query is None else device_query
        self._on_unavailable = on_unavailable
        self._buffer: queue.Queue[bytes] = queue.Queue(maxsize=50)
        self._stream: sd.RawInputStream | None = None
        self._lock = threading.Lock()
        self._state: CaptureState = "stopped"
        self._last_frame_at = 0.0
        self._shutdown = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._unavailable_fired = False
        # Last, so that a rejected volume still leaves cleanup() — which
        # discord.AudioSource.__del__ calls — something valid to work with.
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

    @property
    def state(self) -> CaptureState:
        """Return whether capture is running, re-acquiring, or stopped."""
        with self._lock:
            return self._state

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
        if status is not None and status and not self._status_is_benign(status):
            # Closing the stream here would deadlock — PortAudio forbids it
            # from inside its own callback. The watchdog thread does the work.
            self._signal_loss(f"callback_status={status}")
            return

        self._last_frame_at = time.monotonic()
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

    @staticmethod
    def _status_is_benign(status: sd.CallbackFlags) -> bool:
        """Return whether *status* is the expected under-load overflow."""
        overflowed = bool(getattr(status, "input_overflow", False))
        underflowed = bool(getattr(status, "input_underflow", False))
        return overflowed and not underflowed

    def _on_stream_finished(self) -> None:
        """Called by PortAudio when the stream stops, including on device loss."""
        self._signal_loss("stream_finished")

    def start(self) -> None:
        """Open the PortAudio stream and begin capturing audio."""
        self._require_supported_samplerate(self._device)
        self._open_verified_stream(self._device)
        with self._lock:
            self._state = "running"
        self._start_watchdog()

    @staticmethod
    def _require_supported_samplerate(device: AudioDevice) -> None:
        if device.default_samplerate != SAMPLE_RATE:
            msg = (
                f"Device '{device.name}' runs at "
                f"{device.default_samplerate} Hz, but 48000 Hz is required."
            )
            raise ValueError(msg)

    def _open_verified_stream(self, device: AudioDevice) -> None:
        """Open a stream on *device* and confirm the index is still that device.

        PortAudio's cached device list can name an amp that is already
        unplugged, and its index may now be a microphone. Verifying the live
        name after opening is what keeps a stale index from being streamed.
        """
        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=SAMPLES_PER_FRAME,
            device=device.index,
            callback=self._audio_callback,
            finished_callback=self._on_stream_finished,
        )
        stream.start()

        opened_name = live_device_name(device.index)
        if opened_name is None or self._device_query.lower() not in opened_name.lower():
            self._force_close(stream)
            self._drain_buffer()
            msg = (
                f"Capture device at index {device.index} reports as "
                f"{opened_name!r}, which does not match {self._device_query!r}; "
                "refusing to stream."
            )
            raise DeviceIdentityError(msg)

        with self._lock:
            self._stream = stream
            self._device = device
            self._last_frame_at = time.monotonic()

    def read(self) -> bytes:
        """Return the next 3840-byte PCM frame, or silence on underrun."""
        if self.state != "running":
            return SILENCE

        try:
            data = self._buffer.get(timeout=0.05)
        except queue.Empty:
            return SILENCE

        vol = self.volume
        if vol != 1.0:
            samples = np.frombuffer(data, dtype=np.int16)
            scaled = cast(
                "np.ndarray[Any, np.dtype[np.int16]]",
                np.clip(samples * vol, -32768, 32767).astype(np.int16),
            )
            return scaled.tobytes()
        return data

    def is_opus(self) -> bool:
        """Return False — discord.py handles Opus encoding."""
        return False

    def _signal_loss(self, reason: str) -> None:
        """Mute capture and hand re-acquisition to the watchdog.

        Safe to call from PortAudio's callback thread: it touches no stream.
        """
        with self._lock:
            if self._state != "running":
                return
            self._state = "reacquiring"
            lost_device = self._device.name

        # Frames already queued may have come from the replacement device.
        self._drain_buffer()
        logger.warning("device_lost device=%s reason=%s — muted, re-acquiring", lost_device, reason)

    def _drain_buffer(self) -> None:
        while True:
            try:
                self._buffer.get_nowait()
            except queue.Empty:
                return

    def _start_watchdog(self) -> None:
        if self._watchdog is not None:
            return
        self._shutdown.clear()
        thread = threading.Thread(
            target=self._watchdog_loop,
            name="blackstar-device-watchdog",
            daemon=True,
        )
        self._watchdog = thread
        thread.start()

    def _watchdog_loop(self) -> None:
        give_up_at: float | None = None
        next_attempt_at = 0.0

        while not self._shutdown.wait(WATCHDOG_INTERVAL_SECONDS):
            with self._lock:
                state = self._state
                stream = self._stream
                last_frame_at = self._last_frame_at

            if state == "stopped":
                return

            if state == "running":
                give_up_at = None
                self._check_running_stream(stream, last_frame_at)
                continue

            # Re-acquiring: tear the old stream down before PortAudio is
            # reinitialized, then retry by name on a backoff.
            self._close_stream()
            now = time.monotonic()
            if give_up_at is None:
                give_up_at = now + REACQUIRE_TIMEOUT_SECONDS
                next_attempt_at = now
            if now >= next_attempt_at:
                if self._try_reacquire():
                    give_up_at = None
                    continue
                next_attempt_at = time.monotonic() + RETRY_BACKOFF_SECONDS
            if time.monotonic() >= give_up_at:
                self._give_up()
                return

    def _check_running_stream(self, stream: sd.RawInputStream | None, last_frame_at: float) -> None:
        if stream is not None and not bool(getattr(stream, "active", True)):
            self._signal_loss("stream_inactive")
            return
        if last_frame_at and time.monotonic() - last_frame_at > STARVATION_SECONDS:
            self._signal_loss("no_frames")

    def _try_reacquire(self) -> bool:
        refresh_devices()
        device = find_device_by_name(self._device_query)
        if device is None:
            return False
        if device.default_samplerate != SAMPLE_RATE:
            logger.warning(
                "reacquire_rejected device=%s rate=%s — 48000 Hz is required",
                device.name,
                device.default_samplerate,
            )
            return False

        try:
            self._open_verified_stream(device)
        except Exception:
            logger.warning("reacquire_failed device_query=%s", self._device_query, exc_info=True)
            return False

        with self._lock:
            self._state = "running"
        logger.info("device_reacquired device=%s — audio resumed", device.name)
        return True

    def _give_up(self) -> None:
        with self._lock:
            self._state = "stopped"
            already_fired = self._unavailable_fired
            self._unavailable_fired = True

        logger.error(
            "device_unavailable device_query=%s — gave up after %.0fs",
            self._device_query,
            REACQUIRE_TIMEOUT_SECONDS,
        )
        if already_fired or self._on_unavailable is None:
            return
        try:
            self._on_unavailable()
        except Exception:
            logger.warning("on_unavailable_callback_failed", exc_info=True)

    @staticmethod
    def _force_close(stream: sd.RawInputStream) -> None:
        with contextlib.suppress(Exception):
            stream.stop()
        with contextlib.suppress(Exception):
            stream.close()

    def _close_stream(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            self._force_close(stream)

    def cleanup(self) -> None:
        """Stop capture and release the stream (idempotent, thread-safe)."""
        self._shutdown.set()

        watchdog = self._watchdog
        self._watchdog = None
        # Joining under self._lock would deadlock: the watchdog takes it too.
        if watchdog is not None and watchdog is not threading.current_thread():
            watchdog.join(timeout=WATCHDOG_JOIN_TIMEOUT_SECONDS)

        with self._lock:
            self._state = "stopped"
        self._close_stream()
