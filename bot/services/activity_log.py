from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ActivityLog


def add_activity_log(
    session: AsyncSession,
    *,
    user_id: int | None,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        ActivityLog(
            user_id=user_id,
            action=action,
            details=details,
        )
    )
