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
