from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.callbacks import NavigationCallback
from bot.middlewares.i18n import I18n


def about_keyboard(i18n: I18n, language: str, github_url: str, youtube_url: str, creator_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.github"),
                    url=github_url,
                ),
                InlineKeyboardButton(
                    text=i18n.text(language, "button.youtube"),
                    url=youtube_url,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.creator_telegram"),
                    url=creator_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.back"),
                    callback_data=NavigationCallback(action="back", target="main").pack(),
                )
            ],
        ]
    )
