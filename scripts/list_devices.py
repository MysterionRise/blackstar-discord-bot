#!/usr/bin/env python3
"""List all audio input devices available on this system."""

from __future__ import annotations

from blackstar_bot.device_finder import list_input_devices


def main() -> None:
    """Print all input devices with their index, name, and sample rate."""
    devices = list_input_devices()
    if not devices:
        print("No input devices found.")  # noqa: T201
        return

    print(f"Found {len(devices)} input device(s):\n")  # noqa: T201
    for dev in devices:
        print(  # noqa: T201
            f"  [{dev.index}] {dev.name}"
            f"  (channels={dev.max_input_channels}, rate={dev.default_samplerate})"
        )


if __name__ == "__main__":
    main()
