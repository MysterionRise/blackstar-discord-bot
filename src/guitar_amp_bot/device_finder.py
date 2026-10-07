"""Audio device discovery using sounddevice / PortAudio."""

from __future__ import annotations

import contextlib
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sounddevice as sd

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# Discord voice wants 48 kHz, 16-bit stereo PCM; capture must deliver exactly that.
SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_DTYPE = "int16"

# Device inputs sent to Discord, numbered from 1 as on the device: one input is
# sent to both sides as mono, two are sent as left and right. Amps and
# modellers deliver stereo on inputs 1 and 2; on an audio interface the guitar
# is usually on one input alone.
DEFAULT_INPUT_CHANNELS: tuple[int, ...] = (1, 2)

# Lower ranks win when the same device is listed under several host APIs.
# Windows lists every input under MME too, often truncated and defaulting to
# 44.1 kHz, so the native APIs are preferred over it. Unknown APIs sit between.
_HOSTAPI_RANKS = {
    "windows wasapi": 0,
    "core audio": 0,
    "alsa": 0,
    "jack audio connection kit": 0,
    "windows wdm-ks": 1,
    "windows directsound": 2,
    "mme": 3,
}
_UNKNOWN_HOSTAPI_RANK = 2

# PortAudio is not safe to query while another thread reinitializes it, and
# refresh_devices() does exactly that from the watchdog thread. Every device
# query, re-enumeration and stream open goes through this lock. Reentrant, so
# find_device_by_name() -> list_input_devices() and a stream open that verifies
# the live device name cannot deadlock on themselves.
_PORTAUDIO_LOCK = threading.RLock()

# Capture streams currently open in this process. A refresh that nobody needs
# (listing devices for /devices) must not reinitialize PortAudio under one.
_open_streams = 0


@contextlib.contextmanager
def portaudio_lock() -> Iterator[None]:
    """Hold the process-wide PortAudio lock for a multi-step operation."""
    with _PORTAUDIO_LOCK:
        yield


@dataclass
class AudioDevice:
    """Represents a discovered audio input device."""

    index: int
    name: str
    max_input_channels: int
    default_samplerate: float
    hostapi: str = ""


class AmbiguousDeviceError(LookupError):
    """Raised when a device query matches more than one distinct device."""

    def __init__(self, query: str, candidates: list[str]) -> None:
        self.query = query
        self.candidates = candidates
        names = ", ".join(repr(name) for name in candidates)
        super().__init__(f"{query!r} matches several input devices: {names}")


def validate_input_channels(channels: tuple[int, ...]) -> tuple[int, ...]:
    """Return *channels* if it names one input, or two different inputs.

    Raises:
        ValueError: *channels* is empty, too long, repeats an input, or is not
            numbered from 1.
    """
    if not 1 <= len(channels) <= CHANNELS:
        msg = f"name one input for mono or two for stereo, got {len(channels)}"
        raise ValueError(msg)
    if any(channel < 1 for channel in channels):
        msg = f"inputs are numbered from 1, got {format_input_channels(channels)}"
        raise ValueError(msg)
    if len(set(channels)) != len(channels):
        msg = f"name two different inputs, or one for mono, got {format_input_channels(channels)}"
        raise ValueError(msg)
    return channels


def parse_input_channels(raw: str) -> tuple[int, ...]:
    """Parse an ``INPUT_CHANNELS`` value such as ``"1"`` or ``"1,2"``.

    Raises:
        ValueError: *raw* is not one or two different input numbers.
    """
    try:
        channels = tuple(int(part) for part in raw.split(","))
    except ValueError:
        msg = f"expected one or two input numbers such as '1' or '1,2', got {raw!r}"
        raise ValueError(msg) from None
    return validate_input_channels(channels)


def format_input_channels(channels: tuple[int, ...]) -> str:
    """Return *channels* in the form ``INPUT_CHANNELS`` takes, e.g. ``"1,2"``."""
    return ",".join(str(channel) for channel in channels)


def _hostapi_names() -> list[str]:
    """Return host API names by index, or an empty list if PortAudio fails."""
    try:
        with _PORTAUDIO_LOCK:
            hostapis: Any = sd.query_hostapis()
        return [str(api["name"]) for api in hostapis]
    except Exception:
        logger.warning("PortAudio error while querying host APIs", exc_info=True)
        return []


def list_input_devices() -> list[AudioDevice]:
    """Return all audio input devices available on the system."""
    devices: list[AudioDevice] = []
    try:
        with _PORTAUDIO_LOCK:
            device_list: Any = sd.query_devices()
    except Exception:
        logger.warning("PortAudio error while querying devices", exc_info=True)
        return []
    hostapis = _hostapi_names()
    for i, dev in enumerate(device_list):
        if dev["max_input_channels"] > 0:
            api_index = dev.get("hostapi")
            hostapi = (
                hostapis[api_index]
                if isinstance(api_index, int) and 0 <= api_index < len(hostapis)
                else ""
            )
            devices.append(
                AudioDevice(
                    index=i,
                    name=dev["name"],
                    max_input_channels=dev["max_input_channels"],
                    default_samplerate=dev["default_samplerate"],
                    hostapi=hostapi,
                )
            )
    return devices


def _hostapi_rank(device: AudioDevice) -> int:
    return _HOSTAPI_RANKS.get(device.hostapi.lower(), _UNKNOWN_HOSTAPI_RANK)


def match_devices(devices: list[AudioDevice], query: str) -> list[AudioDevice]:
    """Return the devices *query* names, best host API first.

    An exact (case-insensitive) name match wins over substring matches, so a
    full device name always selects that device even when it is a substring of
    another. Several host APIs listing the same hardware is expected; several
    differently named devices matching within one host API is not, and raises
    :class:`AmbiguousDeviceError` rather than guessing.
    """
    needle = query.lower()
    exact = [device for device in devices if device.name.lower() == needle]
    candidates = exact or [device for device in devices if needle in device.name.lower()]

    names_by_hostapi: dict[str, set[str]] = {}
    for device in candidates:
        names_by_hostapi.setdefault(device.hostapi, set()).add(device.name)
    if any(len(names) > 1 for names in names_by_hostapi.values()):
        distinct = sorted({device.name for device in candidates}, key=str.lower)
        raise AmbiguousDeviceError(query, distinct)

    return sorted(candidates, key=_hostapi_rank)


def capture_problem(
    device: AudioDevice, input_channels: tuple[int, ...] = DEFAULT_INPUT_CHANNELS
) -> str | None:
    """Return why *device* cannot capture *input_channels* for Discord, or None if it can.

    Capture opens every input up to the highest one in *input_channels*. Asks
    PortAudio whether that is supported at 48 kHz instead of trusting
    ``default_samplerate``: plenty of interfaces default to 44.1 kHz but open
    at 48 kHz without complaint.
    """
    needed = max(input_channels)
    if device.max_input_channels < needed:
        hint = (
            " Set INPUT_CHANNELS=1 to capture its single input as mono."
            if device.max_input_channels == 1
            else ""
        )
        return (
            f"'{device.name}' has {device.max_input_channels} input channel(s), "
            f"but {needed} are required for INPUT_CHANNELS="
            f"{format_input_channels(input_channels)}.{hint}"
        )
    try:
        with _PORTAUDIO_LOCK:
            sd.check_input_settings(
                device=device.index,
                channels=needed,
                dtype=SAMPLE_DTYPE,
                samplerate=SAMPLE_RATE,
            )
    except Exception as exc:
        return f"'{device.name}' cannot capture {SAMPLE_RATE} Hz 16-bit audio: {exc}"
    return None


def select_device(
    devices: list[AudioDevice],
    query: str,
    input_channels: tuple[int, ...] = DEFAULT_INPUT_CHANNELS,
) -> AudioDevice | None:
    """Pick the device the bot captures from for *query*, or None if nothing matches.

    Among the matches, the best-ranked host API that can actually capture
    *input_channels* at 48 kHz wins. If none can, the best-ranked match is
    still returned so that opening it fails with a clear reason rather than
    "not found".

    Raises:
        AmbiguousDeviceError: *query* matches several distinct devices.
    """
    candidates = match_devices(devices, query)
    for device in candidates:
        if capture_problem(device, input_channels) is None:
            return device
    return candidates[0] if candidates else None


def find_device_by_name(
    name: str, input_channels: tuple[int, ...] = DEFAULT_INPUT_CHANNELS
) -> AudioDevice | None:
    """Find the input device *name* selects among those present right now.

    Raises:
        AmbiguousDeviceError: *name* matches several distinct devices.
    """
    return select_device(list_input_devices(), name, input_channels)


def refresh_devices() -> None:
    """Re-enumerate PortAudio devices so hot-plug changes become visible.

    PortAudio builds its device list once at initialization, so an unplugged
    amp keeps being reported and its index can meanwhile belong to another
    device — a built-in microphone, for instance. Reinitializing is the only
    way to refresh the list.

    Must be called with no stream open: reinitializing PortAudio underneath a
    live stream is undefined behaviour.
    """
    try:
        with _PORTAUDIO_LOCK:
            sd._terminate()
            sd._initialize()
    except Exception:
        # Non-fatal: callers fall back to the cached list, and the identity
        # check at stream-open time still refuses a mismatched device.
        logger.warning("portaudio_refresh_failed", exc_info=True)


def note_stream_opened() -> None:
    """Record that a capture stream was opened; pair with note_stream_closed()."""
    global _open_streams
    with _PORTAUDIO_LOCK:
        _open_streams += 1


def note_stream_closed() -> None:
    """Record that a capture stream opened earlier has been closed."""
    global _open_streams
    with _PORTAUDIO_LOCK:
        _open_streams = max(0, _open_streams - 1)


def refresh_devices_if_idle() -> bool:
    """Re-enumerate devices unless a capture stream is open; return whether it did.

    For callers that only want a fresh list, such as /devices, and cannot know
    whether a stream is open or still being torn down.
    """
    with _PORTAUDIO_LOCK:
        if _open_streams:
            return False
        refresh_devices()
        return True


def live_device_name(index: int) -> str | None:
    """Return the name PortAudio currently reports at *index*, or None.

    Device indices are positional and shift when devices come and go, so this
    is what makes it possible to confirm an opened stream is the intended
    hardware rather than whatever now occupies the index.
    """
    try:
        with _PORTAUDIO_LOCK:
            info: Any = sd.query_devices(index)
    except Exception:
        logger.warning("portaudio_query_failed index=%s", index, exc_info=True)
        return None

    name = info.get("name") if hasattr(info, "get") else None
    return name if isinstance(name, str) else None
