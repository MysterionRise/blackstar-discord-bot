# Bot Agent

You own the Discord bot commands and configuration.

## Your files
- `src/blackstar_bot/bot.py`
- `src/blackstar_bot/bot_sounddevice.py`
- `src/blackstar_bot/config.py`
- `tests/integration/test_bot_commands.py`

## Constraints
- Use `py-cord` (import as `discord`), not `discord.py`. They share the same
  import name but differ in slash command support.
- All bot commands must handle the case where no voice channel is active
  gracefully (send an informative message, do not crash).
- `config.py` must use `pydantic-settings` (`BaseSettings`) for all
  environment variable loading. No raw `os.getenv()` calls in bot files.
- `signal_type='music'` must always be passed to `voice_client.play()`.
  This optimises the Opus encoder for guitar tone over speech.
- Use `discord.Intents.default()` — no privileged intents needed.
- All public functions require full type annotations.
- Run `ruff check` and `mypy src/blackstar_bot/bot.py` after every edit.

## Config schema (pydantic-settings)
```python
class Settings(BaseSettings):
    discord_token: str
    audio_device: str = "Blackstar"
    audio_device_index: int | None = None
    volume: float = 1.0

    model_config = SettingsConfigDict(env_file=".env")
```
