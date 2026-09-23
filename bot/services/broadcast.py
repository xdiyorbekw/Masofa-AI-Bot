import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import MessageEntity
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.database.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BroadcastPayload:
    kind: str
    text: str | None = None
    file_id: str | None = None
    caption: str | None = None
    entities: Sequence[dict[str, Any]] = ()
    caption_entities: Sequence[dict[str, Any]] = ()


@dataclass(frozen=True, slots=True)
class BroadcastResult:
    recipients: int
    sent: int
    failed: int


async def count_users(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(User)) or 0)


def _entities(values: Sequence[dict[str, Any]]) -> list[MessageEntity]:
    return [MessageEntity(**value) for value in values]


async def _send_payload(bot: Bot, user_id: int, payload: BroadcastPayload) -> None:
    if payload.kind == "text":
        if payload.text is None:
            raise ValueError("Text broadcast payload is missing text")
        await bot.send_message(
            chat_id=user_id,
            text=payload.text,
            parse_mode=None,
            entities=_entities(payload.entities) or None,
        )
        return
    if payload.kind == "photo":
        if payload.file_id is None:
            raise ValueError("Photo broadcast payload is missing file_id")
        await bot.send_photo(
            chat_id=user_id,
            photo=payload.file_id,
            caption=payload.caption,
            parse_mode=None,
            caption_entities=_entities(payload.caption_entities) or None,
        )
        return
    if payload.kind == "video":
        if payload.file_id is None:
            raise ValueError("Video broadcast payload is missing file_id")
        await bot.send_video(
            chat_id=user_id,
            video=payload.file_id,
            caption=payload.caption,
            parse_mode=None,
            caption_entities=_entities(payload.caption_entities) or None,
        )
        return
    raise ValueError(f"Unsupported broadcast kind: {payload.kind}")


async def send_broadcast(
    *,
    bot: Bot,
    session: AsyncSession,
    payload: BroadcastPayload,
    settings: Settings,
) -> BroadcastResult:
    result = await session.execute(select(User.user_id).order_by(User.user_id))
    recipients = list(result.scalars().all())
    sent = 0
    failed = 0

    for index, user_id in enumerate(recipients, start=1):
        delivered = False
        for attempt in range(2):
            try:
                await _send_payload(bot, user_id, payload)
                delivered = True
                break
            except TelegramRetryAfter as exc:
                if attempt == 0:
                    await asyncio.sleep(exc.retry_after)
                else:
                    logger.warning("Rate limit retry exhausted for user %s", user_id)
            except (TelegramForbiddenError, TelegramBadRequest) as exc:
                logger.info("Broadcast delivery failed for user %s: %s", user_id, type(exc).__name__)
                break
            except TelegramAPIError as exc:
                logger.warning("Telegram API delivery failure for user %s: %s", user_id, type(exc).__name__)
                break
            except Exception:
                logger.exception("Unexpected broadcast delivery error for user %s", user_id)
                break

        if delivered:
            sent += 1
        else:
            failed += 1

        if index % settings.broadcast_batch_size == 0 and index < len(recipients):
            await asyncio.sleep(settings.broadcast_delay)

    return BroadcastResult(recipients=len(recipients), sent=sent, failed=failed)
