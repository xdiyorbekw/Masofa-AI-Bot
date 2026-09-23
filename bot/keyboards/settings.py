from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.callbacks import MainMenuCallback, NavigationCallback
from bot.middlewares.i18n import I18n


def settings_keyboard(i18n: I18n, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.change_language"),
                    callback_data=MainMenuCallback(item="change_language").pack(),
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
