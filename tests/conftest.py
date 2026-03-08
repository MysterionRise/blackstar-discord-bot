"""Shared pytest fixtures for Blackstar bot tests."""

import pytest

from blackstar_bot.device_finder import AudioDevice


@pytest.fixture
def fake_device() -> AudioDevice:
    """Return a fake AudioDevice for testing."""
    return AudioDevice(
        index=5,
        name="Blackstar ID:Core V4",
        max_input_channels=2,
        default_samplerate=48000.0,
    )
