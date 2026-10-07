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

from guitar_amp_bot.device_finder import (
    CHANNELS,
    DEFAULT_INPUT_CHANNELS,
    SAMPLE_DTYPE,
    SAMPLE_RATE,
    AmbiguousDeviceError,
    capture_problem,
    find_device_by_name,
    live_device_name,
    note_stream_closed,
    note_stream_opened,
    portaudio_lock,
    refresh_devices,
    validate_input_channels,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from guitar_amp_bot.device_finder import AudioDevice

# Discord expects 48kHz, 16-bit stereo, 20ms frames → 3840 bytes per read().
# The format itself (SAMPLE_RATE, CHANNELS) lives in device_finder, which checks
# devices against it.
FRAME_DURATION_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_DURATION_MS // 1000  # 960
BYTES_PER_FRAME = SAMPLES_PER_FRAME * CHANNELS * 2  # 3840

SILENCE = b"\x00" * BYTES_PER_FRAME

# Capture buffer bounds, in 20 ms frames. The amp's USB clock and the voice
# player's clock drift apart, so the buffer slowly fills; on overrun it is
# trimmed back to the target depth instead of sitting at the ceiling. Latency
# therefore stays between TARGET and MAX frames (40-100 ms).
MAX_BUFFER_FRAMES = 5
TARGET_BUFFER_FRAMES = 2
OVERRUN_LOG_INTERVAL_SECONDS = 10.0

WATCHDOG_INTERVAL_SECONDS = 0.5
STARVATION_SECONDS = 1.0
RETRY_BACKOFF_SECONDS = 2.0
REACQUIRE_TIMEOUT_SECONDS = 60.0
WATCHDOG_JOIN_TIMEOUT_SECONDS = 5.0

CaptureState = Literal["running", "reacquiring", "stopped"]


class DeviceIdentityError(RuntimeError):
    """Raised when an opened stream is not the configured capture device."""


class DeviceAudioSource(discord.AudioSource):  # type: ignore[misc, unused-ignore]
    """Captures PCM audio from a USB amp or audio interface via sounddevice.

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
        input_channels: tuple[int, ...] = DEFAULT_INPUT_CHANNELS,
    ) -> None:
        self._device = device
        # Re-acquisition matches on the name, never the index: the index of a
        # vanished device gets reassigned to an unrelated input.
        self._device_query = device.name if device_query is None else device_query
        self._on_unavailable = on_unavailable
        self._buffer: queue.Queue[bytes] = queue.Queue(maxsize=MAX_BUFFER_FRAMES)
        self._stream: sd.RawInputStream | None = None
        self._lock = threading.Lock()
        self._state: CaptureState = "stopped"
        self._last_frame_at = 0.0
        self._shutdown = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._unavailable_fired = False
        # Overrun bookkeeping; written only from PortAudio's callback thread.
        self._dropped_frames = 0
        self._last_overrun_log = -math.inf
        # Last, so that rejected channels or volume still leave cleanup() —
        # which discord.AudioSource.__del__ calls — something valid to work with.
        self._input_channels = validate_input_channels(input_channels)
        # Capture opens every input up to the highest one wanted, then sends the
        # wanted ones (0-based columns) as left and right. None means the opened
        # block already is exactly that stereo pair.
        self._open_channels = max(input_channels)
        columns = [channel - 1 for channel in input_channels]
        if len(columns) == 1:  # mono: the one input goes to both sides
            columns *= CHANNELS
        self._columns = None if columns == list(range(self._open_channels)) else columns
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
    def input_channels(self) -> tuple[int, ...]:
        """Return the device inputs sent to Discord, numbered from 1."""
        return self._input_channels

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
        data = bytes(indata) if self._columns is None else self._select_inputs(indata)
        try:
            self._buffer.put_nowait(data)
        except queue.Full:
            self._trim_on_overrun()
            with contextlib.suppress(queue.Full):
                self._buffer.put_nowait(data)

    def _select_inputs(self, indata: np.ndarray[Any, np.dtype[np.int16]]) -> bytes:
        """Return the configured inputs of an interleaved block as stereo PCM."""
        frames = np.frombuffer(indata, dtype=np.int16).reshape(-1, self._open_channels)
        stereo = cast("np.ndarray[Any, np.dtype[np.int16]]", frames[:, self._columns])
        return stereo.tobytes()

    def _trim_on_overrun(self) -> None:
        """Drop the oldest frames down to the target depth, logging sparingly.

        Runs on PortAudio's real-time thread, so it logs at most once per
        ``OVERRUN_LOG_INTERVAL_SECONDS`` rather than on every callback.
        """
        while self._buffer.qsize() >= TARGET_BUFFER_FRAMES:
            try:
                self._buffer.get_nowait()
            except queue.Empty:
                break
            self._dropped_frames += 1

        now = time.monotonic()
        if now - self._last_overrun_log >= OVERRUN_LOG_INTERVAL_SECONDS:
            logger.warning(
                "buffer_overrun dropped=%d frames — trimmed capture buffer to %d frames "
                "to keep latency low",
                self._dropped_frames,
                TARGET_BUFFER_FRAMES,
            )
            self._dropped_frames = 0
            self._last_overrun_log = now

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
        problem = capture_problem(self._device, self._input_channels)
        if problem is not None:
            raise ValueError(problem)
        self._open_verified_stream(self._device)
        with self._lock:
            self._state = "running"
        self._start_watchdog()

    def _open_verified_stream(self, device: AudioDevice) -> None:
        """Open a stream on *device* and confirm the index is still that device.

        PortAudio's cached device list can name an amp that is already
        unplugged, and its index may now be a microphone. Verifying the live
        name after opening is what keeps a stale index from being streamed.
        The name must be the selected device's exact name: a loose query such
        as "USB" would otherwise accept whatever USB input took the index.

        Held under the PortAudio lock throughout, so a re-enumeration cannot
        land between opening the index and checking what it now names.
        """
        with portaudio_lock():
            stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                channels=self._open_channels,
                dtype=SAMPLE_DTYPE,
                blocksize=SAMPLES_PER_FRAME,
                device=device.index,
                callback=self._audio_callback,
                finished_callback=self._on_stream_finished,
            )
            note_stream_opened()
            try:
                stream.start()
                opened_name = live_device_name(device.index)
                if opened_name is None or opened_name.lower() != device.name.lower():
                    msg = (
                        f"Capture device at index {device.index} reports as "
                        f"{opened_name!r}, not {device.name!r}; refusing to stream."
                    )
                    raise DeviceIdentityError(msg)
            except BaseException:
                self._force_close(stream)
                self._drain_buffer()
                raise

        with self._lock:
            self._stream = stream
            self._device = device
            self._last_frame_at = time.monotonic()

    def read(self) -> bytes:
        """Return the next 3840-byte PCM frame, or silence on underrun."""
        if self.state != "running":
            return SILENCE

        # Never block: the voice player calls this every 20 ms and a late frame
        # stalls its timing loop. An empty buffer plays a frame of silence.
        try:
            data = self._buffer.get_nowait()
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
            name="guitar-amp-bot-device-watchdog",
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
        try:
            device = find_device_by_name(self._device_query, self._input_channels)
        except AmbiguousDeviceError as exc:
            logger.warning("reacquire_ambiguous candidates=%s", exc.candidates)
            return False
        if device is None:
            return False
        problem = capture_problem(device, self._input_channels)
        if problem is not None:
            logger.warning("reacquire_rejected device=%s — %s", device.name, problem)
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
        """Stop and close *stream*; called exactly once per opened stream."""
        with contextlib.suppress(Exception):
            stream.stop()
        with contextlib.suppress(Exception):
            stream.close()
        note_stream_closed()

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
