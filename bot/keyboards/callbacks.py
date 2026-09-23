from aiogram.filters.callback_data import CallbackData


class NavigationCallback(CallbackData, prefix="nav"):
    action: str
    target: str = ""


class MainMenuCallback(CallbackData, prefix="menu"):
    item: str


class LanguageCallback(CallbackData, prefix="lang"):
    code: str


class WeatherCallback(CallbackData, prefix="weather"):
    action: str
    region: str = ""


class AdminCallback(CallbackData, prefix="admin"):
    action: str
    page: int = 0


class BroadcastCallback(CallbackData, prefix="broadcast"):
    action: str
