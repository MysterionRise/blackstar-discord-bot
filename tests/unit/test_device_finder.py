"""Tests for blackstar_bot.device_finder."""

import logging
from unittest.mock import patch

from blackstar_bot.device_finder import (
    find_device_by_name,
    list_input_devices,
    live_device_name,
    refresh_devices,
)

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


@patch("blackstar_bot.device_finder.sd.query_devices", return_value=FAKE_DEVICES[1])
def test_live_device_name_returns_name_at_index(_mock):
    """The live name at an index backs the stream identity check."""
    assert live_device_name(1) == "Blackstar ID:Core V4"


@patch("blackstar_bot.device_finder.sd.query_devices", side_effect=RuntimeError("boom"))
def test_live_device_name_returns_none_on_portaudio_error(_mock):
    """A query failure must not raise: the caller treats None as a mismatch."""
    assert live_device_name(1) is None


@patch("blackstar_bot.device_finder.sd._initialize")
@patch("blackstar_bot.device_finder.sd._terminate")
def test_refresh_devices_reinitializes_portaudio(mock_terminate, mock_initialize):
    """Re-enumeration is the only way PortAudio notices a hot-unplug."""
    refresh_devices()
    mock_terminate.assert_called_once()
    mock_initialize.assert_called_once()


@patch("blackstar_bot.device_finder.sd._terminate", side_effect=RuntimeError("boom"))
def test_refresh_devices_survives_portaudio_error(_mock, caplog):
    """A failed refresh is logged and non-fatal; the identity check still guards."""
    with caplog.at_level(logging.WARNING, logger="blackstar_bot.device_finder"):
        refresh_devices()
    assert any("portaudio_refresh_failed" in r.message for r in caplog.records)
