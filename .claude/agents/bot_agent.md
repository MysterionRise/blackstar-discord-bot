# Bot Agent

You own the Discord bot commands, configuration, authorization and startup.

## Your files
- `src/guitar_amp_bot/bot_sounddevice.py`
- `src/guitar_amp_bot/config.py`
- `src/guitar_amp_bot/authz.py`
- `src/guitar_amp_bot/startup.py`
- `src/guitar_amp_bot/logging_setup.py`
- `src/guitar_amp_bot/setup_wizard.py`
- `tests/integration/**` and the matching `tests/unit/` files

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
- Every slash command starts with `require_owner(ctx, ...)` from `authz.py`.
  The owner is the only user who may touch the host's audio hardware.
- Replies that name hardware, paths or exception text are `ephemeral=True`.
  Only the "streaming started" and "stopped streaming" replies are public.
  Unprompted channel notices (auto-stop, device lost, playback error) carry no
  device name or exception detail; that detail goes to the log.
- `/stream` takes no arguments: the device and backend come from settings only.
- One stream per instance: `_active_streams` plus the `_stream_starting` flag.
  The stream auto-stops 30 s after the owner leaves or the channel empties.
- Blocking PortAudio work (device lookup, re-scan, `source.start()`,
  `source.cleanup()`) runs via `asyncio.to_thread`, never on the event loop.
- All public functions require full type annotations.
- Run `ruff check` and `mypy src/guitar_amp_bot/bot_sounddevice.py` after every edit.

## Config schema (pydantic-settings)
`src/guitar_amp_bot/config.py` is the source of truth. At the time of writing it
contains:
```python
class Settings(BaseSettings):
    discord_token: str
    owner_id: int | None = Field(default=None, gt=0)  # None: the application owner
    guild_id: int | None = Field(default=None, gt=0)  # None: commands in every server
    audio_device: str = Field(min_length=1)  # required; blank is rejected
    audio_backend: Literal["sounddevice", "ffmpeg"] = "sounddevice"
    debug_config: bool = False
    log_file: Path | None = Path("guitar-amp-bot.log")  # empty LOG_FILE: stderr only
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    volume: float = Field(default=1.0, ge=0.0, le=5.0)

    model_config = SettingsConfigDict(env_file=".env")
```
A new setting also needs a line in `.env.example` and a row in the README's
Settings table.
