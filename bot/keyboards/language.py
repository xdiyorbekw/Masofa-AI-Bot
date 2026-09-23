from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.callbacks import LanguageCallback, NavigationCallback
from bot.middlewares.i18n import I18n


def language_keyboard(i18n: I18n, language: str, include_back: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=i18n.text(language, "language_options.ru"),
                callback_data=LanguageCallback(code="ru").pack(),
            ),
            InlineKeyboardButton(
                text=i18n.text(language, "language_options.uz"),
                callback_data=LanguageCallback(code="uz").pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text=i18n.text(language, "language_options.en"),
                callback_data=LanguageCallback(code="en").pack(),
            )
        ],
    ]
    if include_back:
        rows.append(
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.back"),
                    callback_data=NavigationCallback(action="back", target="main").pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
