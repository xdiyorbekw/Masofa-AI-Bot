from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.callbacks import AdminCallback, BroadcastCallback
from bot.middlewares.i18n import I18n


def admin_dashboard_keyboard(i18n: I18n, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "admin.button.metrics"),
                    callback_data=AdminCallback(action="metrics").pack(),
                ),
                InlineKeyboardButton(
                    text=i18n.text(language, "admin.button.logs"),
                    callback_data=AdminCallback(action="logs", page=0).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "admin.button.broadcast"),
                    callback_data=BroadcastCallback(action="start").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "admin.button.logout"),
                    callback_data=AdminCallback(action="logout").pack(),
                )
            ],
        ]
    )


def admin_logs_keyboard(i18n: I18n, language: str, page: int, has_previous: bool, has_next: bool) -> InlineKeyboardMarkup:
    navigation: list[InlineKeyboardButton] = []
    if has_previous:
        navigation.append(
            InlineKeyboardButton(
                text=i18n.text(language, "button.previous"),
                callback_data=AdminCallback(action="logs", page=page - 1).pack(),
            )
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(
                text=i18n.text(language, "button.next"),
                callback_data=AdminCallback(action="logs", page=page + 1).pack(),
            )
        )

    rows = [navigation] if navigation else []
    rows.append(
        [
            InlineKeyboardButton(
                text=i18n.text(language, "button.back"),
                callback_data=AdminCallback(action="dashboard").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_confirmation_keyboard(i18n: I18n, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.text(language, "button.confirm"),
                    callback_data=BroadcastCallback(action="confirm").pack(),
                ),
                InlineKeyboardButton(
                    text=i18n.text(language, "button.cancel"),
                    callback_data=BroadcastCallback(action="cancel").pack(),
                ),
            ]
        ]
    )
