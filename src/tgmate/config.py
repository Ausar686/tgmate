"""Bot settings loaded from the environment and `.env`."""

import pydantic
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///data/tgmate.db"


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
