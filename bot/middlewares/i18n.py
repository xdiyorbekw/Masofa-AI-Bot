import json
from pathlib import Path
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import SUPPORTED_LANGUAGES
from bot.database.models import User


class I18n:
    """Loads locale dictionaries and provides strict translation lookup."""

    def __init__(self, locales_dir: Path) -> None:
        self.locales_dir = locales_dir
        self.translations: dict[str, dict[str, Any]] = {}
        self._load()
        self._validate_keys()

    def _load(self) -> None:
        for language in sorted(SUPPORTED_LANGUAGES):
            path = self.locales_dir / f"{language}.json"
            with path.open("r", encoding="utf-8") as file:
                self.translations[language] = json.load(file)

    def _flatten_keys(self, data: dict[str, Any], prefix: str = "") -> set[str]:
        keys: set[str] = set()
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                keys.update(self._flatten_keys(value, full_key))
            else:
                keys.add(full_key)
        return keys

    def _validate_keys(self) -> None:
        key_sets = {
            language: self._flatten_keys(data)
            for language, data in self.translations.items()
        }
        first = next(iter(key_sets.values()))
        for language, keys in key_sets.items():
            if keys != first:
                missing = sorted(first - keys)
                extra = sorted(keys - first)
                raise ValueError(
                    f"Locale key mismatch for {language}: missing={missing}, extra={extra}"
                )

    def text(self, language: str, key: str, **kwargs: Any) -> str:
        if language not in self.translations:
            raise ValueError(f"Unsupported application language: {language}")
        value: Any = self.translations[language]
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                raise KeyError(f"Missing translation key: {key}")
            value = value[part]
        if not isinstance(value, str):
            raise TypeError(f"Translation key is not a string: {key}")
        return value.format(**kwargs)


async def resolve_language(
    session: AsyncSession,
    telegram_user_id: int | None,
    state_language: str | None,
    default_language: str,
) -> str:
    if telegram_user_id is not None:
        user_language = await session.scalar(
            select(User.language_code).where(User.user_id == telegram_user_id)
        )
        if user_language in SUPPORTED_LANGUAGES:
            return user_language
    if state_language in SUPPORTED_LANGUAGES:
        return state_language
    return default_language


class I18nMiddleware(BaseMiddleware):
    """Inject the user's saved language and shared I18n service."""

    def __init__(self, i18n: I18n, default_language: str) -> None:
        self.i18n = i18n
        self.default_language = default_language

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]):
        session: AsyncSession = data["session"]
        from_user = getattr(event, "from_user", None)
        state = data.get("state")
        state_language: str | None = None
        if state is not None:
            state_data = await state.get_data()
            state_language = state_data.get("language")
        language = await resolve_language(
            session=session,
            telegram_user_id=from_user.id if from_user else None,
            state_language=state_language,
            default_language=self.default_language,
        )
        data["i18n"] = self.i18n
        data["language"] = language
        return await handler(event, data)
