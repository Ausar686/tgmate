"""Bot settings loaded from the environment and `.env`."""

import typing as t

import pydantic
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///data/tgmate.db"
# Telegram's hosted Bot API lets bots download files up to 20 MB and send files up to 50 MB; a Bot API server of
# the bot's own, in local mode, takes and sends files up to 2000 MB.
HOSTED_DOWNLOAD_LIMIT_MB = 20
HOSTED_UPLOAD_LIMIT_MB = 50
LOCAL_FILE_LIMIT_MB = 2000


class DatabaseSettings(BaseSettings):
    """The subset migrations need, so `alembic` runs without bot credentials."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # A server URL can embed a password; SecretStr keeps it out of reprs and logs like the bot token.
    database_url: pydantic.SecretStr = pydantic.SecretStr(DEFAULT_DATABASE_URL)


class Settings(DatabaseSettings):
    telegram_bot_token: pydantic.SecretStr
    # The only user who can approve others; always allowed to use the bot.
    owner_user_id: int
    log_level: str = "INFO"
    # Where the bot's users can get its source code, as the AGPL requires: a modified deployment points this at its
    # own published source.
    source_url: str = "https://github.com/Ausar686/tgmate"
    # A Bot API server of the bot's own, run with `--local` (docs/deployment.md); unset, Telegram's hosted one.
    telegram_api_url: pydantic.HttpUrl | None = None
    # The largest file users can send. Files are converted in memory, so a higher limit needs more of it.
    download_limit_mb: pydantic.PositiveInt = HOSTED_DOWNLOAD_LIMIT_MB

    @property
    def upload_limit_mb(self) -> int:
        """The largest file the bot can send, which only the Bot API server decides."""
        return HOSTED_UPLOAD_LIMIT_MB if self.telegram_api_url is None else LOCAL_FILE_LIMIT_MB

    @pydantic.model_validator(mode="after")
    def _check_download_limit(self) -> t.Self:
        if self.telegram_api_url is None and self.download_limit_mb > HOSTED_DOWNLOAD_LIMIT_MB:
            raise ValueError(f"download_limit_mb can be at most {HOSTED_DOWNLOAD_LIMIT_MB} without TELEGRAM_API_URL")
        if self.download_limit_mb > LOCAL_FILE_LIMIT_MB:
            raise ValueError(f"download_limit_mb can be at most {LOCAL_FILE_LIMIT_MB}")
        return self
