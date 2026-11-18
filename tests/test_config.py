import pydantic
import pytest

from tgmate.config import DEFAULT_DATABASE_URL, DatabaseSettings, Settings

REQUIRED = {"TELEGRAM_BOT_TOKEN": "123:abc", "OWNER_USER_ID": "42"}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key in ("DATABASE_URL", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_reads_required_values_and_defaults(env: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None)

    assert settings.telegram_bot_token.get_secret_value() == "123:abc"
    assert settings.owner_user_id == 42
    assert settings.database_url.get_secret_value() == DEFAULT_DATABASE_URL
    assert settings.log_level == "INFO"


def test_empty_values_fall_back_to_defaults(env: pytest.MonkeyPatch) -> None:
    env.setenv("DATABASE_URL", "")

    assert Settings(_env_file=None).database_url.get_secret_value() == DEFAULT_DATABASE_URL


@pytest.mark.parametrize("missing", sorted(REQUIRED))
def test_missing_required_value_is_an_error(env: pytest.MonkeyPatch, missing: str) -> None:
    env.delenv(missing)

    with pytest.raises(pydantic.ValidationError, match=missing.lower()):
        Settings(_env_file=None)


def test_secrets_stay_out_of_repr(env: pytest.MonkeyPatch) -> None:
    env.setenv("DATABASE_URL", "postgresql+asyncpg://bot:hunter2@db/tgmate")

    assert "123:abc" not in repr(Settings(_env_file=None))
    assert "hunter2" not in repr(Settings(_env_file=None))


def test_database_settings_need_no_bot_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in REQUIRED:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x.db")

    assert DatabaseSettings(_env_file=None).database_url.get_secret_value() == "sqlite+aiosqlite:///x.db"
