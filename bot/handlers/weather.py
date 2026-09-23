import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User
from bot.keyboards.callbacks import MainMenuCallback, NavigationCallback, WeatherCallback
from bot.keyboards.weather import weather_forecast_keyboard, weather_regions_keyboard
from bot.middlewares.i18n import I18n
from bot.services.activity_log import add_activity_log
from bot.services.weather_api import WeatherService, WeatherServiceError, WEATHER_REGIONS, condition_key

logger = logging.getLogger(__name__)
router = Router(name="weather")


def _region_by_id(region_id: str):
    for region in WEATHER_REGIONS:
        if region.id == region_id:
            return region
    return None


@router.callback_query(MainMenuCallback.filter(F.item == "weather"))
async def weather_menu_callback(
    callback: CallbackQuery,
    callback_data: MainMenuCallback,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    language: str,
) -> None:
    if callback_data.item != "weather":
        return
    user = await session.get(User, callback.from_user.id)
    if user is None:
        await callback.answer(i18n.text(language, "errors.registration_required"), show_alert=True)
        return
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            i18n.text(language, "weather.select_region"),
            reply_markup=weather_regions_keyboard(i18n, language),
        )


@router.callback_query(WeatherCallback.filter())
async def weather_callback(
    callback: CallbackQuery,
    callback_data: WeatherCallback,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    language: str,
    weather_service: WeatherService,
) -> None:
    user = await session.get(User, callback.from_user.id)
    if user is None:
        await callback.answer(i18n.text(language, "errors.registration_required"), show_alert=True)
        return

    if callback_data.action == "regions":
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(
                i18n.text(language, "weather.select_region"),
                reply_markup=weather_regions_keyboard(i18n, language),
            )
        return

    if callback_data.action != "region":
        await callback.answer()
        return

    region = _region_by_id(callback_data.region)
    if region is None:
        await callback.answer(i18n.text(language, "errors.invalid_region"), show_alert=True)
        return

    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            i18n.text(language, "weather.loading", region=i18n.text(language, region.locale_key)),
            reply_markup=weather_forecast_keyboard(i18n, language),
        )
    add_activity_log(session, user_id=user.user_id, action="weather_request", details={"region": region.id})
    await session.commit()

    try:
        forecast = await weather_service.get_7_day_forecast(region)
    except WeatherServiceError:
        logger.warning("Weather request failed for region %s", region.id, exc_info=True)
        if callback.message:
            await callback.message.edit_text(
                i18n.text(language, "weather.unavailable"),
                reply_markup=weather_regions_keyboard(i18n, language),
            )
        return

    region_name = html.escape(i18n.text(language, region.locale_key))
    blocks: list[str] = [i18n.text(language, "weather.forecast_title", region=region_name)]
    date_format = i18n.text(language, "meta.date_format")
    for day in forecast.days:
        weekday = i18n.text(language, f"day_names.{day.date_local.weekday()}")
        date_text = day.date_local.strftime(date_format)
        condition_name = i18n.text(language, f"weather.condition.{condition_key(day.weather_id)}")
        condition_icon = i18n.text(language, f"weather.icon.{condition_key(day.weather_id)}")
        min_temp = i18n.text(
            language,
            "weather.temperature_value",
            value=f"{day.temperature_min:.0f}" if day.temperature_min is not None else i18n.text(language, "weather.missing"),
        )
        max_temp = i18n.text(
            language,
            "weather.temperature_value",
            value=f"{day.temperature_max:.0f}" if day.temperature_max is not None else i18n.text(language, "weather.missing"),
        )
        humidity = i18n.text(
            language,
            "weather.humidity_value",
            value=day.humidity if day.humidity is not None else i18n.text(language, "weather.missing"),
        )
        wind = i18n.text(
            language,
            "weather.wind_value",
            value=f"{day.wind_speed:.1f}" if day.wind_speed is not None else i18n.text(language, "weather.missing"),
        )
        blocks.append(
            i18n.text(
                language,
                "weather.day_block",
                weekday=html.escape(weekday),
                date=date_text,
                icon=condition_icon,
                condition=html.escape(condition_name),
                min_temp=min_temp,
                max_temp=max_temp,
                humidity=humidity,
                wind=wind,
            )
        )

    if callback.message:
        await callback.message.edit_text(
            "\n\n".join(blocks),
            reply_markup=weather_forecast_keyboard(i18n, language),
        )
