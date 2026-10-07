"""Discord Guitar Amp Bot — streams a USB amp into Discord voice channels."""

from importlib.metadata import PackageNotFoundError, version

try:
    # pyproject.toml is the single source of the version.
    __version__ = version("discord-guitar-amp-bot")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"
