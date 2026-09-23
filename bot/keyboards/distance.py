from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.callbacks import NavigationCallback
from bot.middlewares.i18n import I18n


def distance_keyboard(i18n: I18n, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.cancel"),
                    callback_data=NavigationCallback(action="main").pack(),
                )
            ]
        ]
    )


def destination_keyboard(i18n: I18n, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.cancel"),
                    callback_data=NavigationCallback(action="main").pack(),
                )
            ]
        ]
    )
