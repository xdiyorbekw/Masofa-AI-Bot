from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.callbacks import NavigationCallback, WeatherCallback
from bot.middlewares.i18n import I18n
from bot.services.weather_api import WEATHER_REGIONS


def weather_regions_keyboard(i18n: I18n, language: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(WEATHER_REGIONS), 2):
        row: list[InlineKeyboardButton] = []
        for region in WEATHER_REGIONS[index:index + 2]:
            row.append(
                InlineKeyboardButton(
                    text=i18n.text(language, region.locale_key),
                    callback_data=WeatherCallback(action="region", region=region.id).pack(),
                )
            )
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text=i18n.text(language, "button.main_menu"),
                callback_data=NavigationCallback(action="main").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def weather_forecast_keyboard(i18n: I18n, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.back"),
                    callback_data=WeatherCallback(action="regions").pack(),
                ),
                InlineKeyboardButton(
                    text=i18n.text(language, "button.main_menu"),
                    callback_data=NavigationCallback(action="main").pack(),
                ),
            ]
        ]
    )
