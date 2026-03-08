"""Pydantic-based settings loaded from environment variables / .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bot configuration sourced from environment variables."""

    discord_token: str
    audio_device: str = "Blackstar"
    audio_device_index: int | None = None
    volume: float = 1.0

    model_config = SettingsConfigDict(env_file=".env")
