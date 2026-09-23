from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User
from bot.keyboards.callbacks import MainMenuCallback
from bot.keyboards.language import language_keyboard
from bot.keyboards.settings import settings_keyboard
from bot.middlewares.i18n import I18n

router = Router(name="settings")


@router.callback_query(MainMenuCallback.filter(F.item == "settings"))
async def settings_callback(
    callback: CallbackQuery,
    callback_data: MainMenuCallback,
    session: AsyncSession,
    i18n: I18n,
    language: str,
) -> None:
    if callback_data.item != "settings":
        return
    user = await session.get(User, callback.from_user.id)
    if user is None:
        await callback.answer(i18n.text(language, "errors.registration_required"), show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            i18n.text(language, "settings.text"),
            reply_markup=settings_keyboard(i18n, language),
        )


@router.callback_query(MainMenuCallback.filter(F.item == "change_language"))
async def change_language_callback(
    callback: CallbackQuery,
    callback_data: MainMenuCallback,
    session: AsyncSession,
    i18n: I18n,
    language: str,
) -> None:
    if callback_data.item != "change_language":
        return
    user = await session.get(User, callback.from_user.id)
    if user is None:
        await callback.answer(i18n.text(language, "errors.registration_required"), show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            i18n.text(language, "language.select"),
            reply_markup=language_keyboard(i18n, language, include_back=True),
        )
