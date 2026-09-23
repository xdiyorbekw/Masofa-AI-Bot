import html
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.database.models import User
from bot.keyboards.callbacks import LanguageCallback
from bot.keyboards.language import language_keyboard
from bot.keyboards.main import main_menu
from bot.middlewares.i18n import I18n
from bot.services.activity_log import add_activity_log
from bot.states.registration import RegistrationStates

logger = logging.getLogger(__name__)
router = Router(name="start")

_NAME_ALLOWED_EXTRA = {" ", "-", "'", "’", "ʻ", "ʼ", "‘", "`"}


def _is_valid_full_name(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value.strip())
    if not 3 <= len(normalized) <= 100:
        return False
    words = normalized.split(" ")
    if len(words) < 2:
        return False
    if any(char.isdigit() for char in normalized):
        return False
    if not all(char.isalpha() or char in _NAME_ALLOWED_EXTRA for char in normalized):
        return False
    return sum(char.isalpha() for char in normalized) >= 2


async def _show_registration_language(message: Message, state: FSMContext, i18n: I18n, language: str) -> None:
    await state.clear()
    await state.set_state(RegistrationStates.waiting_language)
    await message.answer(
        i18n.text(language, "registration.choose_language"),
        reply_markup=language_keyboard(i18n, language),
    )


@router.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    language: str,
    settings: Settings,
) -> None:
    telegram_user = message.from_user
    if telegram_user is None:
        return
    user = await session.get(User, telegram_user.id)
    if user is None:
        await state.clear()
        await state.set_state(RegistrationStates.waiting_language)
        await state.update_data(language=settings.default_language)
        await message.answer(
            i18n.text(settings.default_language, "registration.choose_language"),
            reply_markup=language_keyboard(i18n, settings.default_language),
        )
        return

    await state.clear()
    display_name = html.escape(user.full_name)
    await message.answer(
        i18n.text(user.language_code, "app.greeting", full_name=display_name),
        reply_markup=main_menu(i18n, user.language_code),
    )


@router.message(Command("menu"))
async def menu_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    settings: Settings,
) -> None:
    telegram_user = message.from_user
    if telegram_user is None:
        return
    user = await session.get(User, telegram_user.id)
    if user is None:
        await state.clear()
        await state.set_state(RegistrationStates.waiting_language)
        await state.update_data(language=settings.default_language)
        await message.answer(
            i18n.text(settings.default_language, "registration.choose_language"),
            reply_markup=language_keyboard(i18n, settings.default_language),
        )
        return
    await state.clear()
    await message.answer(
        i18n.text(user.language_code, "app.greeting", full_name=html.escape(user.full_name)),
        reply_markup=main_menu(i18n, user.language_code),
    )


@router.callback_query(LanguageCallback.filter())
async def registration_language_callback(
    callback: CallbackQuery,
    callback_data: LanguageCallback,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
) -> None:
    await callback.answer()
    new_language = callback_data.code
    current_state = await state.get_state()
    telegram_user = callback.from_user
    if telegram_user is None or new_language not in {"ru", "uz", "en"}:
        await callback.answer(i18n.text("ru", "errors.generic"), show_alert=True)
        return

    if current_state == RegistrationStates.waiting_language.state:
        await state.update_data(language=new_language)
        await state.set_state(RegistrationStates.waiting_full_name)
        if callback.message:
            await callback.message.edit_text(
                i18n.text(new_language, "registration.ask_full_name"),
                reply_markup=None,
            )
        return

    user = await session.get(User, telegram_user.id)
    if user is None:
        await state.clear()
        await state.set_state(RegistrationStates.waiting_language)
        await state.update_data(language=new_language)
        if callback.message:
            await callback.message.edit_text(
                i18n.text(new_language, "registration.choose_language"),
                reply_markup=language_keyboard(i18n, new_language),
            )
        return

    old_language = user.language_code
    user.language_code = new_language
    add_activity_log(
        session,
        user_id=user.user_id,
        action="language_change",
        details={"from": old_language, "to": new_language},
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            i18n.text(new_language, "language.changed"),
            reply_markup=main_menu(i18n, new_language),
        )


@router.message(RegistrationStates.waiting_language, F.text == "/cancel")
@router.message(RegistrationStates.waiting_full_name, F.text == "/cancel")
async def registration_cancel_handler(
    message: Message,
    state: FSMContext,
    i18n: I18n,
) -> None:
    await state.clear()
    await state.set_state(RegistrationStates.waiting_language)
    await state.update_data(language="ru")
    await message.answer(
        i18n.text("ru", "registration.choose_language"),
        reply_markup=language_keyboard(i18n, "ru"),
    )


@router.message(RegistrationStates.waiting_full_name)
async def registration_name_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
) -> None:
    telegram_user = message.from_user
    if telegram_user is None:
        return
    text = message.text or ""
    if not _is_valid_full_name(text):
        data = await state.get_data()
        language = data.get("language", "ru")
        await message.answer(i18n.text(language, "registration.invalid_name"))
        return

    data = await state.get_data()
    language = data.get("language", "ru")
    normalized_name = re.sub(r"\s+", " ", text.strip())
    existing = await session.get(User, telegram_user.id)
    if existing is not None:
        await state.clear()
        await message.answer(
            i18n.text(existing.language_code, "app.greeting", full_name=html.escape(existing.full_name)),
            reply_markup=main_menu(i18n, existing.language_code),
        )
        return

    user = User(
        user_id=telegram_user.id,
        full_name=normalized_name,
        username=telegram_user.username,
        language_code=language,
    )
    session.add(user)
    add_activity_log(
        session,
        user_id=telegram_user.id,
        action="registration",
        details={"language": language},
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        user = await session.scalar(select(User).where(User.user_id == telegram_user.id))
        if user is None:
            raise
        await state.clear()
        await message.answer(
            i18n.text(user.language_code, "app.greeting", full_name=html.escape(user.full_name)),
            reply_markup=main_menu(i18n, user.language_code),
        )
        return

    await state.clear()
    await message.answer(
        i18n.text(language, "registration.success", full_name=html.escape(normalized_name)),
        reply_markup=main_menu(i18n, language),
    )
    logger.info("Registered Telegram user %s", telegram_user.id)
