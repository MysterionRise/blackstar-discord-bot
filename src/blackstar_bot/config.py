"""Pydantic-based settings loaded from environment variables / .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AudioBackend = Literal["sounddevice", "ffmpeg"]


class Settings(BaseSettings):
    """Bot configuration sourced from environment variables."""

    discord_token: str
    owner_id: int = Field(gt=0)
    guild_id: int | None = Field(default=None, gt=0)
    audio_device: str = "Blackstar"
    audio_backend: AudioBackend = "sounddevice"
    debug_config: bool = False
    log_file: Path | None = Path("blackstar-bot.log")
    volume: float = Field(default=1.0, ge=0.0, le=5.0)

    model_config = SettingsConfigDict(env_file=".env")

    @field_validator("log_file", mode="before")
    @classmethod
    def _blank_disables_log_file(cls: type[Settings], value: object) -> object:
        """Treat an empty ``LOG_FILE`` as "no file logging" rather than a blank path."""
        if isinstance(value, str) and not value.strip():
            return None
        return value
