"""Pydantic-based settings loaded from environment variables / .env file."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AudioBackend = Literal["sounddevice", "ffmpeg"]


class Settings(BaseSettings):
    """Bot configuration sourced from environment variables."""

    discord_token: str
    audio_device: str = "Blackstar"
    audio_backend: AudioBackend = "sounddevice"
    debug_config: bool = False
    volume: float = Field(default=1.0, ge=0.0, le=5.0)

    model_config = SettingsConfigDict(env_file=".env")
