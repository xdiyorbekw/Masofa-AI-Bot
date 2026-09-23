import html
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User
from bot.keyboards.callbacks import NavigationCallback
from bot.keyboards.main import main_menu
from bot.middlewares.i18n import I18n
from bot.states.admin import AdminStates
from bot.states.distance import DistanceStates
from bot.states.registration import RegistrationStates

logger = logging.getLogger(__name__)
router = Router(name="common")


async def render_main_menu_from_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
) -> None:
    telegram_user = callback.from_user
    if telegram_user is None:
        return
    user = await session.get(User, telegram_user.id)
    if user is None:
        await state.clear()
        await state.set_state(RegistrationStates.waiting_language)
        await state.update_data(language="ru")
        if callback.message:
            from bot.keyboards.language import language_keyboard

            await callback.message.edit_text(
                i18n.text("ru", "registration.choose_language"),
                reply_markup=language_keyboard(i18n, "ru"),
            )
        return
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            i18n.text(user.language_code, "app.greeting", full_name=html.escape(user.full_name)),
            reply_markup=main_menu(i18n, user.language_code),
        )


@router.callback_query(NavigationCallback.filter())
async def navigation_callback(
    callback: CallbackQuery,
    callback_data: NavigationCallback,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
) -> None:
    if callback_data.action == "main" or (callback_data.action == "back" and callback_data.target == "main"):
        await callback.answer()
        await render_main_menu_from_callback(callback, state, session, i18n)
        return
    await callback.answer()


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext, session: AsyncSession, i18n: I18n) -> None:
    telegram_user = message.from_user
    if telegram_user is None:
        return
    current_state = await state.get_state()
    if current_state and current_state.startswith(AdminStates.__name__):
        await state.clear()
        await message.answer(i18n.text("ru", "admin.session_cancelled"))
        return
    await state.clear()
    user = await session.get(User, telegram_user.id)
    if user is None:
        await message.answer(i18n.text("ru", "registration.choose_language"))
        return
    await message.answer(
        i18n.text(user.language_code, "common.cancelled"),
        reply_markup=main_menu(i18n, user.language_code),
    )
