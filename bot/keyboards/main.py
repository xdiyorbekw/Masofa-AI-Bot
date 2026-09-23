from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.callbacks import MainMenuCallback
from bot.middlewares.i18n import I18n


def main_menu(i18n: I18n, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.weather"),
                    callback_data=MainMenuCallback(item="weather").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.distance"),
                    callback_data=MainMenuCallback(item="distance").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.about"),
                    callback_data=MainMenuCallback(item="about").pack(),
                ),
                InlineKeyboardButton(
                    text=i18n.text(language, "button.settings"),
                    callback_data=MainMenuCallback(item="settings").pack(),
                ),
            ],
        ]
    )
