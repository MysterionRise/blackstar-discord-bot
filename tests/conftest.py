"""Shared pytest fixtures for Blackstar bot tests."""

import pytest

import blackstar_bot.bot_sounddevice as bot_module
from blackstar_bot import device_finder
from blackstar_bot.device_finder import AudioDevice


@pytest.fixture(autouse=True)
def isolate_portaudio_state(monkeypatch):
    """Start every test with no capture streams open and no real /devices refresh."""
    monkeypatch.setattr(device_finder, "_open_streams", 0)
    monkeypatch.setattr(bot_module, "refresh_devices_if_idle", lambda: False)


@pytest.fixture
def fake_device() -> AudioDevice:
    """Return a fake AudioDevice for testing."""
    return AudioDevice(
        index=5,
        name="Blackstar ID:Core V4",
        max_input_channels=2,
        default_samplerate=48000.0,
    )
