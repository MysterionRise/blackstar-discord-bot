"""Pydantic-based settings loaded from environment variables / .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from guitar_amp_bot.device_finder import (
    DEFAULT_INPUT_CHANNELS,
    parse_input_channels,
    validate_input_channels,
)

AudioBackend = Literal["sounddevice", "ffmpeg"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    """Bot configuration sourced from environment variables."""

    discord_token: str
    # Optional: left unset, the bot authorizes the owner of its own Discord
    # application, which is who created the token in the first place.
    owner_id: int | None = Field(default=None, gt=0)
    guild_id: int | None = Field(default=None, gt=0)
    # Required, with no default: a generic default ("USB", say) could match the
    # wrong input, and only audio from the chosen device may ever be streamed.
    audio_device: str = Field(min_length=1)
    # "1,2" (stereo, the default), "1" (mono to both sides) or e.g. "3,4".
    # NoDecode: the environment value is "1,2", not JSON.
    input_channels: Annotated[tuple[int, ...], NoDecode] = DEFAULT_INPUT_CHANNELS
    audio_backend: AudioBackend = "sounddevice"
    debug_config: bool = False
    log_file: Path | None = Path("guitar-amp-bot.log")
    log_level: LogLevel = "INFO"
    volume: float = Field(default=1.0, ge=0.0, le=5.0)

    model_config = SettingsConfigDict(env_file=".env")

    @field_validator("audio_device", mode="before")
    @classmethod
    def _strip_audio_device(cls: type[Settings], value: object) -> object:
        """Reject a blank ``AUDIO_DEVICE``: as a substring it would match every input."""
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("input_channels", mode="before")
    @classmethod
    def _parse_input_channels(cls: type[Settings], value: object) -> object:
        """Read ``INPUT_CHANNELS=1,2`` as the inputs it names."""
        if isinstance(value, str):
            return parse_input_channels(value)
        return value

    @field_validator("input_channels")
    @classmethod
    def _check_input_channels(cls: type[Settings], value: tuple[int, ...]) -> tuple[int, ...]:
        return validate_input_channels(value)

    @field_validator("log_file", mode="before")
    @classmethod
    def _blank_disables_log_file(cls: type[Settings], value: object) -> object:
        """Treat an empty ``LOG_FILE`` as "no file logging" rather than a blank path."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls: type[Settings], value: object) -> object:
        """Accept ``LOG_LEVEL=debug`` as well as ``LOG_LEVEL=DEBUG``."""
        if isinstance(value, str):
            return value.strip().upper()
        return value
