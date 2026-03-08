"""Tests for blackstar_bot.device_finder."""

from unittest.mock import patch

from blackstar_bot.device_finder import find_device_by_name, list_input_devices

FAKE_DEVICES = [
    {"name": "Built-in Microphone", "max_input_channels": 1, "default_samplerate": 44100.0},
    {"name": "Blackstar ID:Core V4", "max_input_channels": 2, "default_samplerate": 48000.0},
    {"name": "HDMI Output", "max_input_channels": 0, "default_samplerate": 48000.0},
]


@patch("blackstar_bot.device_finder.sd.query_devices", return_value=FAKE_DEVICES)
def test_list_input_devices_filters_outputs(_mock):
    """Only devices with input channels should be returned."""
    devices = list_input_devices()
    assert len(devices) == 2
    assert all(d.max_input_channels > 0 for d in devices)


@patch("blackstar_bot.device_finder.sd.query_devices", return_value=FAKE_DEVICES)
def test_find_device_by_name_case_insensitive(_mock):
    """Device search should be case-insensitive."""
    device = find_device_by_name("blackstar")
    assert device is not None
    assert device.name == "Blackstar ID:Core V4"


@patch("blackstar_bot.device_finder.sd.query_devices", return_value=FAKE_DEVICES)
def test_find_device_by_name_returns_none_for_unknown(_mock):
    """Unknown device names should return None."""
    device = find_device_by_name("Nonexistent Device")
    assert device is None
