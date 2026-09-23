import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault, ErrorEvent, Message

from bot.config import Settings, load_settings
from bot.database.connection import Database
from bot.handlers import about, admin, common, distance, settings as settings_handler, start, weather
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.i18n import I18n, I18nMiddleware
from bot.services.weather_api import WeatherService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def configure_bot_commands(bot: Bot, i18n: I18n, default_language: str) -> None:
    for language in ("ru", "uz", "en"):
        commands = [
            BotCommand(command="start", description=i18n.text(language, "commands.start")),
            BotCommand(command="menu", description=i18n.text(language, "commands.menu")),
            BotCommand(command="admin", description=i18n.text(language, "commands.admin")),
            BotCommand(command="cancel", description=i18n.text(language, "commands.cancel")),
        ]
        await bot.set_my_commands(
            commands,
            scope=BotCommandScopeDefault(),
            language_code=language,
        )

    default_commands = [
        BotCommand(command="start", description=i18n.text(default_language, "commands.start")),
        BotCommand(command="menu", description=i18n.text(default_language, "commands.menu")),
        BotCommand(command="admin", description=i18n.text(default_language, "commands.admin")),
        BotCommand(command="cancel", description=i18n.text(default_language, "commands.cancel")),
    ]
    await bot.set_my_commands(default_commands, scope=BotCommandScopeDefault())


async def main() -> None:
    settings = load_settings()
    logger.info("Starting Telegram bot")

    database = Database(settings.database_url)
    i18n = I18n(Path(__file__).parent / "locales")
    weather_service = WeatherService(settings.request_timeout)
    await database.initialize()
    await weather_service.start()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["settings"] = settings
    dispatcher["database"] = database
    dispatcher["i18n"] = i18n
    dispatcher["weather_service"] = weather_service

    db_middleware = DbSessionMiddleware(database.session_factory)
    i18n_middleware = I18nMiddleware(i18n, settings.default_language)
    dispatcher.message.outer_middleware(db_middleware)
    dispatcher.message.outer_middleware(i18n_middleware)
    dispatcher.callback_query.outer_middleware(db_middleware)
    dispatcher.callback_query.outer_middleware(i18n_middleware)

    error_router = Router(name="errors")

    @error_router.error()
    async def global_error_handler(event: ErrorEvent, bot: Bot, database: Database, i18n: I18n) -> None:
        exception = event.exception
        logger.error(
            "Unhandled update exception: %s",
            type(exception).__name__,
            exc_info=(type(exception), exception, exception.__traceback__),
        )
        update = event.update
        message: Message | None = update.message or update.edited_message
        callback = update.callback_query
        user_id = None
        if message and message.from_user:
            user_id = message.from_user.id
        elif callback and callback.from_user:
            user_id = callback.from_user.id
        language = "ru"
        if user_id is not None:
            async with database.session_factory() as session:
                from sqlalchemy import select

                from bot.database.models import User

                user_language = await session.scalar(select(User.language_code).where(User.user_id == user_id))
                if user_language in {"ru", "uz", "en"}:
                    language = user_language
        text = i18n.text(language, "errors.generic")
        try:
            if callback is not None:
                await callback.answer(text, show_alert=True)
            elif message is not None:
                await message.answer(text)
        except TelegramAPIError:
            logger.warning("Could not send global error message", exc_info=True)

    dispatcher.include_router(error_router)
    dispatcher.include_router(start.router)
    dispatcher.include_router(weather.router)
    dispatcher.include_router(distance.router)
    dispatcher.include_router(about.router)
    dispatcher.include_router(settings_handler.router)
    dispatcher.include_router(admin.router)
    dispatcher.include_router(common.router)

    await configure_bot_commands(bot, i18n, settings.default_language)
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dispatcher.start_polling(bot, close_bot_session=False)
    finally:
        logger.info("Shutting down Telegram bot")
        await weather_service.close()
        await bot.session.close()
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
