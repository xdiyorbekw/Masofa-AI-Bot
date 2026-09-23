from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.database.models import User
from bot.keyboards.about import about_keyboard
from bot.keyboards.callbacks import MainMenuCallback
from bot.middlewares.i18n import I18n

router = Router(name="about")


@router.callback_query(MainMenuCallback.filter(F.item == "about"))
async def about_callback(
    callback: CallbackQuery,
    callback_data: MainMenuCallback,
    session: AsyncSession,
    i18n: I18n,
    language: str,
    settings: Settings,
) -> None:
    if callback_data.item != "about":
        return
    user = await session.get(User, callback.from_user.id)
    if user is None:
        await callback.answer(i18n.text(language, "errors.registration_required"), show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            i18n.text(language, "about.text"),
            reply_markup=about_keyboard(
                i18n,
                language,
                settings.github_url,
                settings.youtube_url,
                settings.creator_telegram_url,
            ),
        )
