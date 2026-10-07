"""Shared pytest fixtures for the bot tests."""

import os

import pytest

from guitar_amp_bot.config import Settings

# bot_sounddevice resolves GUILD_IDS from Settings when it is imported, so a
# developer's .env or exported variables would otherwise decide how the suite
# registers commands. Settings must see neither, and this has to happen before
# that import. Tests that need a setting pass it explicitly.
Settings.model_config["env_file"] = None
for _field in Settings.model_fields:
    os.environ.pop(_field.upper(), None)

import guitar_amp_bot.bot_sounddevice as bot_module  # noqa: E402
from guitar_amp_bot import device_finder  # noqa: E402
from guitar_amp_bot.device_finder import AudioDevice  # noqa: E402


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
