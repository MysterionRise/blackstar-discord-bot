"""Audio device discovery using sounddevice / PortAudio."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import sounddevice as sd

logger = logging.getLogger(__name__)


@dataclass
class AudioDevice:
    """Represents a discovered audio input device."""

    index: int
    name: str
    max_input_channels: int
    default_samplerate: float


def list_input_devices() -> list[AudioDevice]:
    """Return all audio input devices available on the system."""
    devices: list[AudioDevice] = []
    try:
        device_list: Any = sd.query_devices()
    except Exception:
        logger.warning("PortAudio error while querying devices", exc_info=True)
        return []
    for i, dev in enumerate(device_list):
        if dev["max_input_channels"] > 0:
            devices.append(
                AudioDevice(
                    index=i,
                    name=dev["name"],
                    max_input_channels=dev["max_input_channels"],
                    default_samplerate=dev["default_samplerate"],
                )
            )
    return devices


def find_device_by_name(name: str) -> AudioDevice | None:
    """Find the first input device whose name contains *name* (case-insensitive)."""
    needle = name.lower()
    for device in list_input_devices():
        if needle in device.name.lower():
            return device
    return None


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
        sd._terminate()
        sd._initialize()
    except Exception:
        # Non-fatal: callers fall back to the cached list, and the identity
        # check at stream-open time still refuses a mismatched device.
        logger.warning("portaudio_refresh_failed", exc_info=True)


def live_device_name(index: int) -> str | None:
    """Return the name PortAudio currently reports at *index*, or None.

    Device indices are positional and shift when devices come and go, so this
    is what makes it possible to confirm an opened stream is the intended
    hardware rather than whatever now occupies the index.
    """
    try:
        info: Any = sd.query_devices(index)
    except Exception:
        logger.warning("portaudio_query_failed index=%s", index, exc_info=True)
        return None

    name = info.get("name") if hasattr(info, "get") else None
    return name if isinstance(name, str) else None
