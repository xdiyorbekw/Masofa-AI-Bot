import hmac
import html
import json
import logging
import time
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.database.models import ActivityLog, User
from bot.keyboards.admin import (
    admin_dashboard_keyboard,
    admin_logs_keyboard,
    broadcast_confirmation_keyboard,
)
from bot.keyboards.callbacks import AdminCallback, BroadcastCallback
from bot.middlewares.i18n import I18n
from bot.services.activity_log import add_activity_log
from bot.services.broadcast import BroadcastPayload, count_users, send_broadcast
from bot.states.admin import AdminStates

logger = logging.getLogger(__name__)
router = Router(name="admin")

MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 900
LOGS_PER_PAGE = 8
ADMIN_STATES = (
    AdminStates.waiting_username,
    AdminStates.waiting_password,
    AdminStates.authenticated,
    AdminStates.waiting_broadcast_content,
    AdminStates.waiting_broadcast_confirmation,
)


def _admin_language(data: dict[str, Any], settings: Settings) -> str:
    language = data.get("language")
    return language if language in {"ru", "uz", "en"} else settings.default_language


async def _check_identity(user_id: int, settings: Settings) -> bool:
    return settings.admin_telegram_id is None or settings.admin_telegram_id == user_id


async def _get_admin_session_data(state: FSMContext) -> dict[str, Any] | None:
    data = await state.get_data()
    admin_user_id = data.get("admin_user_id")
    if not isinstance(admin_user_id, int):
        return None
    return data


async def _ensure_authenticated(
    *,
    user_id: int,
    state: FSMContext,
    settings: Settings,
) -> bool:
    """Authorize the admin independently of the current FSM step."""
    if not await _check_identity(user_id, settings):
        return False

    data = await _get_admin_session_data(state)
    if data is None or data.get("admin_user_id") != user_id:
        return False

    last_activity = float(data.get("last_activity", 0.0))
    if time.time() - last_activity > settings.admin_session_timeout:
        await state.clear()
        return False

    await state.update_data(last_activity=time.time())
    return True


async def _start_admin_auth(
    message: Message,
    state: FSMContext,
    i18n: I18n,
    settings: Settings,
) -> None:
    await state.clear()
    await state.set_state(AdminStates.waiting_username)
    await state.update_data(
        language=settings.default_language,
        admin_user_id=message.from_user.id,
        failed_attempts=0,
        locked_until=0.0,
    )
    await message.answer(i18n.text(settings.default_language, "admin.ask_username"))


async def _register_login_failure(state: FSMContext) -> tuple[bool, int]:
    data = await state.get_data()
    attempts = int(data.get("failed_attempts", 0)) + 1
    if attempts >= MAX_LOGIN_ATTEMPTS:
        user_id = data.get("admin_user_id")
        await state.clear()
        await state.set_state(AdminStates.waiting_username)
        await state.update_data(
            language=data.get("language"),
            admin_user_id=user_id,
            locked_until=time.time() + LOGIN_LOCK_SECONDS,
            failed_attempts=attempts,
        )
        return True, attempts
    await state.update_data(failed_attempts=attempts)
    return False, attempts


async def _login_is_locked(state: FSMContext) -> int:
    data = await state.get_data()
    locked_until = float(data.get("locked_until", 0.0))
    remaining = int(max(0.0, locked_until - time.time()))
    if remaining <= 0 and locked_until:
        await state.update_data(locked_until=0.0, failed_attempts=0)
        return 0
    return remaining


async def _dashboard(
    *,
    message: Message | None,
    callback: CallbackQuery | None,
    i18n: I18n,
    language: str,
) -> None:
    markup = admin_dashboard_keyboard(i18n, language)
    text = i18n.text(language, "admin.dashboard")
    if message is not None:
        await message.answer(text, reply_markup=markup)
    elif callback is not None and callback.message is not None:
        await callback.message.edit_text(text, reply_markup=markup)


@router.message(Command("cancel"), StateFilter(*ADMIN_STATES))
async def admin_cancel_command(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    settings: Settings,
) -> None:
    data = await state.get_data()
    language = _admin_language(data, settings)
    if data.get("admin_user_id") == message.from_user.id and await state.get_state() == AdminStates.authenticated.state:
        add_activity_log(session, user_id=message.from_user.id, action="admin_logout", details=None)
        await session.commit()
    await state.clear()
    await message.answer(i18n.text(language, "admin.session_cancelled"))


@router.message(Command("admin"))
async def admin_command_handler(
    message: Message,
    state: FSMContext,
    i18n: I18n,
    settings: Settings,
) -> None:
    if message.chat.type != "private":
        await message.answer(i18n.text(settings.default_language, "admin.private_chat_only"))
        return

    if not await _check_identity(message.from_user.id, settings):
        await message.answer(i18n.text(settings.default_language, "admin.unauthorized"))
        return

    data = await state.get_data()
    if await _ensure_authenticated(user_id=message.from_user.id, state=state, settings=settings):
        language = _admin_language(data, settings)
        await state.update_data(broadcast_payload=None, last_activity=time.time())
        await state.set_state(AdminStates.authenticated)
        await _dashboard(message=message, callback=None, i18n=i18n, language=language)
        return

    remaining = await _login_is_locked(state)
    if remaining > 0:
        language = _admin_language(data, settings)
        await message.answer(i18n.text(language, "admin.locked", seconds=remaining))
        return

    await _start_admin_auth(message, state, i18n, settings)


@router.message(AdminStates.waiting_username)
async def admin_username_handler(
    message: Message,
    state: FSMContext,
    i18n: I18n,
    settings: Settings,
) -> None:
    if not await _check_identity(message.from_user.id, settings):
        await state.clear()
        await message.answer(i18n.text(settings.default_language, "admin.unauthorized"))
        return

    data = await state.get_data()
    language = _admin_language(data, settings)
    remaining = await _login_is_locked(state)
    if remaining > 0:
        await message.answer(i18n.text(language, "admin.locked", seconds=remaining))
        return

    username = (message.text or "").strip()
    if not username:
        locked, _ = await _register_login_failure(state)
        if locked:
            await message.answer(i18n.text(language, "admin.locked", seconds=LOGIN_LOCK_SECONDS))
            return
        await message.answer(i18n.text(language, "admin.invalid_credentials"))
        return

    await state.update_data(username=username)
    await state.set_state(AdminStates.waiting_password)
    await message.answer(i18n.text(language, "admin.ask_password"))


@router.message(AdminStates.waiting_password)
async def admin_password_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    settings: Settings,
) -> None:
    if not await _check_identity(message.from_user.id, settings):
        await state.clear()
        await message.answer(i18n.text(settings.default_language, "admin.unauthorized"))
        return

    data = await state.get_data()
    language = _admin_language(data, settings)
    username = str(data.get("username", ""))
    password = message.text or ""
    username_ok = hmac.compare_digest(username, settings.admin_username)
    password_ok = hmac.compare_digest(password, settings.admin_password)

    if not (username_ok and password_ok):
        locked, _ = await _register_login_failure(state)
        if locked:
            await message.answer(i18n.text(language, "admin.locked", seconds=LOGIN_LOCK_SECONDS))
        else:
            await message.answer(i18n.text(language, "admin.invalid_credentials"))
        return

    await state.update_data(
        admin_user_id=message.from_user.id,
        last_activity=time.time(),
        language=language,
        failed_attempts=0,
        locked_until=0.0,
    )
    await state.set_state(AdminStates.authenticated)
    add_activity_log(session, user_id=message.from_user.id, action="admin_login", details=None)
    await session.commit()
    await message.answer(i18n.text(language, "admin.login_success"))
    await _dashboard(message=message, callback=None, i18n=i18n, language=language)
    logger.info("Admin authenticated user_id=%s", message.from_user.id)


@router.callback_query(AdminCallback.filter())
async def admin_callback_handler(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    settings: Settings,
) -> None:
    if not await _ensure_authenticated(user_id=callback.from_user.id, state=state, settings=settings):
        await callback.answer(i18n.text(settings.default_language, "admin.unauthorized"), show_alert=True)
        return

    data = await state.get_data()
    language = _admin_language(data, settings)
    await callback.answer()

    if callback_data.action == "dashboard":
        await state.set_state(AdminStates.authenticated)
        await _dashboard(message=None, callback=callback, i18n=i18n, language=language)
        return

    if callback_data.action == "metrics":
        total_users = await session.scalar(select(func.count()).select_from(User))
        total_logs = await session.scalar(select(func.count()).select_from(ActivityLog))
        rows = await session.execute(
            select(User.language_code, func.count(User.user_id)).group_by(User.language_code)
        )
        language_lines = [
            i18n.text(language, "admin.metrics_language_line", lang=lang, count=count)
            for lang, count in rows.all()
        ]
        message_text = i18n.text(
            language,
            "admin.metrics",
            total_users=int(total_users or 0),
            total_logs=int(total_logs or 0),
            language_counts="\n".join(language_lines) if language_lines else i18n.text(language, "admin.no_data"),
        )
        if callback.message:
            await callback.message.edit_text(
                message_text,
                reply_markup=admin_logs_keyboard(i18n, language, 0, False, False),
            )
        return

    if callback_data.action == "logs":
        page = max(0, callback_data.page)
        total = int(await session.scalar(select(func.count()).select_from(ActivityLog)) or 0)
        offset = page * LOGS_PER_PAGE
        if offset >= total and total > 0:
            page = max(0, (total - 1) // LOGS_PER_PAGE)
            offset = page * LOGS_PER_PAGE
        rows = await session.execute(
            select(ActivityLog, User.full_name)
            .outerjoin(User, ActivityLog.user_id == User.user_id)
            .order_by(desc(ActivityLog.timestamp))
            .offset(offset)
            .limit(LOGS_PER_PAGE)
        )
        entries: list[str] = []
        for log, full_name in rows.all():
            details = i18n.text(language, "admin.no_details")
            if log.details:
                details = json.dumps(log.details, ensure_ascii=False, separators=(", ", ": "))
            user_label = (
                html.escape(full_name)
                if full_name
                else html.escape(str(log.user_id))
                if log.user_id
                else i18n.text(language, "admin.no_user")
            )
            entries.append(
                i18n.text(
                    language,
                    "admin.log_entry",
                    timestamp=log.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    user=user_label,
                    action=html.escape(log.action),
                    details=html.escape(details[:500]),
                )
            )
        content = i18n.text(
            language,
            "admin.logs",
            page=page + 1,
            total_pages=max(1, (total + LOGS_PER_PAGE - 1) // LOGS_PER_PAGE),
            entries="\n\n".join(entries) if entries else i18n.text(language, "admin.no_data"),
        )
        if callback.message:
            await callback.message.edit_text(
                content,
                reply_markup=admin_logs_keyboard(
                    i18n,
                    language,
                    page,
                    page > 0,
                    offset + LOGS_PER_PAGE < total,
                ),
            )
        return

    if callback_data.action == "logout":
        add_activity_log(session, user_id=callback.from_user.id, action="admin_logout", details=None)
        await session.commit()
        await state.clear()
        if callback.message:
            await callback.message.edit_text(i18n.text(language, "admin.logged_out"))
        logger.info("Admin logged out user_id=%s", callback.from_user.id)


@router.callback_query(BroadcastCallback.filter())
async def broadcast_callback_handler(
    callback: CallbackQuery,
    callback_data: BroadcastCallback,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    settings: Settings,
) -> None:
    if not await _ensure_authenticated(user_id=callback.from_user.id, state=state, settings=settings):
        await callback.answer(i18n.text(settings.default_language, "admin.unauthorized"), show_alert=True)
        return

    data = await state.get_data()
    language = _admin_language(data, settings)

    if callback_data.action == "start":
        await callback.answer()
        await state.set_state(AdminStates.waiting_broadcast_content)
        if callback.message:
            await callback.message.edit_text(i18n.text(language, "admin.broadcast_ask"))
        return

    if callback_data.action == "cancel":
        await callback.answer()
        await state.update_data(broadcast_payload=None, last_activity=time.time())
        await state.set_state(AdminStates.authenticated)
        if callback.message:
            await callback.message.edit_text(
                i18n.text(language, "admin.dashboard"),
                reply_markup=admin_dashboard_keyboard(i18n, language),
            )
        return

    if callback_data.action != "confirm":
        return

    if await state.get_state() != AdminStates.waiting_broadcast_confirmation.state:
        await callback.answer(i18n.text(language, "admin.broadcast_missing"), show_alert=True)
        return

    payload_data = data.get("broadcast_payload")
    if not isinstance(payload_data, dict):
        await callback.answer(i18n.text(language, "admin.broadcast_missing"), show_alert=True)
        return

    payload = BroadcastPayload(
        kind=str(payload_data.get("kind")),
        text=payload_data.get("text"),
        file_id=payload_data.get("file_id"),
        caption=payload_data.get("caption"),
        entities=tuple(payload_data.get("entities", ())),
        caption_entities=tuple(payload_data.get("caption_entities", ())),
    )
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(i18n.text(language, "admin.broadcast_started"))

    add_activity_log(
        session,
        user_id=callback.from_user.id,
        action="broadcast_started",
        details={"kind": payload.kind},
    )
    await session.commit()

    try:
        result = await send_broadcast(
            bot=callback.bot,
            session=session,
            payload=payload,
            settings=settings,
        )
    except Exception:
        logger.exception("Broadcast failed unexpectedly for admin user_id=%s", callback.from_user.id)
        add_activity_log(
            session,
            user_id=callback.from_user.id,
            action="broadcast_finished",
            details={"status": "error", "kind": payload.kind},
        )
        await session.commit()
        result = None
    finally:
        await state.update_data(broadcast_payload=None, last_activity=time.time())
        await state.set_state(AdminStates.authenticated)

    if result is None:
        if callback.message:
            await callback.message.edit_text(
                i18n.text(language, "admin.broadcast_failed"),
                reply_markup=admin_dashboard_keyboard(i18n, language),
            )
        return

    add_activity_log(
        session,
        user_id=callback.from_user.id,
        action="broadcast_finished",
        details={"recipients": result.recipients, "sent": result.sent, "failed": result.failed},
    )
    await session.commit()

    if callback.message:
        await callback.message.edit_text(
            i18n.text(
                language,
                "admin.broadcast_finished",
                recipients=result.recipients,
                sent=result.sent,
                failed=result.failed,
            ),
            reply_markup=admin_dashboard_keyboard(i18n, language),
        )


@router.message(AdminStates.waiting_broadcast_content, F.content_type.in_({"text", "photo", "video"}))
async def broadcast_content_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    settings: Settings,
) -> None:
    if not await _ensure_authenticated(user_id=message.from_user.id, state=state, settings=settings):
        await message.answer(i18n.text(settings.default_language, "admin.unauthorized"))
        return

    data = await state.get_data()
    language = _admin_language(data, settings)

    kind = "text"
    payload: dict[str, Any] = {"kind": "text", "entities": (), "caption_entities": ()}
    preview = message.text or ""

    if message.photo:
        kind = "photo"
        preview = message.caption or ""
        payload.update(
            {
                "kind": kind,
                "file_id": message.photo[-1].file_id,
                "caption": message.caption,
                "caption_entities": tuple(
                    entity.model_dump(mode="python") for entity in (message.caption_entities or ())
                ),
            }
        )
    elif message.video:
        kind = "video"
        preview = message.caption or ""
        payload.update(
            {
                "kind": kind,
                "file_id": message.video.file_id,
                "caption": message.caption,
                "caption_entities": tuple(
                    entity.model_dump(mode="python") for entity in (message.caption_entities or ())
                ),
            }
        )
    else:
        payload["text"] = message.text
        payload["entities"] = tuple(
            entity.model_dump(mode="python") for entity in (message.entities or ())
        )

    if kind == "text" and len(message.text or "") > 4096:
        await message.answer(i18n.text(language, "admin.broadcast_text_too_long"))
        return
    if kind in {"photo", "video"} and len(message.caption or "") > 1024:
        await message.answer(i18n.text(language, "admin.broadcast_caption_too_long"))
        return

    recipients = await count_users(session)
    payload["preview"] = preview[:500]
    payload["recipients"] = recipients
    await state.update_data(broadcast_payload=payload, last_activity=time.time())
    await state.set_state(AdminStates.waiting_broadcast_confirmation)

    kind_label = i18n.text(language, f"admin.broadcast_kind.{kind}")
    preview_html = html.escape(preview[:500]) if preview else i18n.text(language, "admin.broadcast_no_caption")
    await message.answer(
        i18n.text(
            language,
            "admin.broadcast_confirmation",
            kind=kind_label,
            recipients=recipients,
            preview=preview_html,
        ),
        reply_markup=broadcast_confirmation_keyboard(i18n, language),
    )


@router.message(AdminStates.waiting_broadcast_content)
async def unsupported_broadcast_content_handler(
    message: Message,
    state: FSMContext,
    i18n: I18n,
    settings: Settings,
) -> None:
    if not await _ensure_authenticated(user_id=message.from_user.id, state=state, settings=settings):
        await message.answer(i18n.text(settings.default_language, "admin.unauthorized"))
        return
    language = _admin_language(await state.get_data(), settings)
    await message.answer(i18n.text(language, "admin.broadcast_unsupported"))
