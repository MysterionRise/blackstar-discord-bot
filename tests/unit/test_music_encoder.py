"""Tests for the Opus music-encoding hint."""

from unittest.mock import MagicMock, patch

from blackstar_bot.bot_sounddevice import _prepare_music_encoder


def test_prepare_music_encoder_installs_music_signal_type():
    """py-cord only builds its own encoder when one is not already set."""
    vc = MagicMock()
    encoder = MagicMock()

    with patch("blackstar_bot.bot_sounddevice.discord.opus.Encoder", return_value=encoder):
        _prepare_music_encoder(vc)

    encoder.set_signal_type.assert_called_once_with("music")
    assert vc.encoder is encoder


def test_prepare_music_encoder_survives_missing_libopus():
    """A missing libopus must degrade encoding quality, not stop the stream."""
    vc = MagicMock()

    with patch(
        "blackstar_bot.bot_sounddevice.discord.opus.Encoder",
        side_effect=RuntimeError("libopus not loaded"),
    ):
        _prepare_music_encoder(vc)  # must not raise
