from typing import Final
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_LANGUAGES: Final[frozenset[str]] = frozenset({"uz", "ru", "en"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: str = Field(validation_alias="BOT_TOKEN", min_length=1)
    database_url: str = Field(validation_alias="DATABASE_URL", min_length=1)

    admin_username: str = Field(validation_alias="ADMIN_USERNAME", min_length=1)
    admin_password: str = Field(validation_alias="ADMIN_PASSWORD", min_length=1)
    admin_telegram_id: int | None = Field(default=None, validation_alias="ADMIN_TELEGRAM_ID")

    github_url: str = Field(validation_alias="GITHUB_URL", min_length=1)
    youtube_url: str = Field(validation_alias="YOUTUBE_URL", min_length=1)
    creator_telegram_url: str = Field(validation_alias="CREATOR_TELEGRAM_URL", min_length=1)

    default_language: str = Field(default="ru", validation_alias="DEFAULT_LANGUAGE")
    admin_session_timeout: int = Field(default=1800, validation_alias="ADMIN_SESSION_TIMEOUT", gt=0)
    broadcast_batch_size: int = Field(default=20, validation_alias="BROADCAST_BATCH_SIZE", gt=0)
    broadcast_delay: float = Field(default=1.0, validation_alias="BROADCAST_DELAY", ge=0)
    request_timeout: float = Field(default=15.0, validation_alias="REQUEST_TIMEOUT", gt=0)


    @field_validator("admin_telegram_id", mode="before")
    @classmethod
    def empty_admin_telegram_id_to_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    @field_validator("default_language")
    @classmethod
    def validate_default_language(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_LANGUAGES:
            supported = ", ".join(sorted(SUPPORTED_LANGUAGES))
            raise ValueError(f"DEFAULT_LANGUAGE must be one of: {supported}")
        return normalized

    @field_validator("github_url", "youtube_url", "creator_telegram_url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Social URLs must be valid http(s) URLs")
        return value.strip()


def load_settings() -> Settings:
    return Settings()
