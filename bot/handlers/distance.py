import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User
from bot.keyboards.callbacks import MainMenuCallback
from bot.keyboards.distance import destination_keyboard, distance_keyboard
from bot.middlewares.i18n import I18n
from bot.services.activity_log import add_activity_log
from bot.services.distance_calc import Coordinates, adjusted_walking_speed, haversine_distance, parse_coordinates, walking_time_minutes
from bot.services.weather_api import WeatherService, WeatherServiceError, condition_key
from bot.states.distance import DistanceStates

logger = logging.getLogger(__name__)
router = Router(name="distance")


@router.callback_query(MainMenuCallback.filter(F.item == "distance"))
async def distance_menu_callback(
    callback: CallbackQuery,
    callback_data: MainMenuCallback,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    language: str,
) -> None:
    if callback_data.item != "distance":
        return
    user = await session.get(User, callback.from_user.id)
    if user is None:
        await callback.answer(i18n.text(language, "errors.registration_required"), show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await state.set_state(DistanceStates.waiting_start)
    if callback.message:
        await callback.message.edit_text(
            i18n.text(language, "distance.ask_start"),
            reply_markup=distance_keyboard(i18n, language),
        )


async def _handle_location(
    *,
    latitude: float,
    longitude: float,
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    language: str,
    weather_service: WeatherService,
) -> None:
    location = Coordinates(latitude=latitude, longitude=longitude)
    current_state = await state.get_state()
    if current_state == DistanceStates.waiting_start.state:
        await state.update_data(start_latitude=location.latitude, start_longitude=location.longitude)
        await state.set_state(DistanceStates.waiting_destination)
        await message.answer(
            i18n.text(language, "distance.ask_destination"),
            reply_markup=destination_keyboard(i18n, language),
        )
        return

    if current_state != DistanceStates.waiting_destination.state:
        return

    data = await state.get_data()
    start_latitude = data.get("start_latitude")
    start_longitude = data.get("start_longitude")
    if start_latitude is None or start_longitude is None:
        await state.clear()
        await message.answer(i18n.text(language, "distance.state_lost"))
        return

    start = Coordinates(float(start_latitude), float(start_longitude))
    distance_km = haversine_distance(start, location)

    current_weather = None
    weather_error = False
    try:
        current_weather = await weather_service.get_current_weather(start.latitude, start.longitude)
    except WeatherServiceError:
        weather_error = True
        logger.warning("Current weather unavailable for distance calculation", exc_info=True)

    if current_weather is None:
        adjusted_speed = 5.0
        walking_minutes = walking_time_minutes(distance_km, adjusted_speed)
        weather_text = i18n.text(language, "distance.weather_unavailable")
        adjustment_text = i18n.text(language, "distance.adjustment_unavailable")
        advice = i18n.text(language, "distance.advice.normal")
    else:
        adjusted_speed, adjustment = adjusted_walking_speed(
            temperature_c=current_weather.temperature_c,
            weather_id=current_weather.weather_id,
        )
        walking_minutes = walking_time_minutes(distance_km, adjusted_speed)
        condition = condition_key(current_weather.weather_id)
        condition_name = i18n.text(language, f"weather.condition.{condition}")
        icon = i18n.text(language, f"weather.icon.{condition}")
        temperature = i18n.text(
            language,
            "weather.temperature_value",
            value=f"{current_weather.temperature_c:.0f}" if current_weather.temperature_c is not None else i18n.text(language, "weather.missing"),
        )
        weather_text = i18n.text(
            language,
            "distance.current_weather",
            temperature=temperature,
            icon=icon,
            condition=condition_name,
        )
        adjustment_text = i18n.text(
            language,
            f"distance.adjustment.{adjustment.reason_key}",
            percent=round((1.0 - adjustment.multiplier) * 100),
        )
        advice = i18n.text(language, f"distance.advice.{adjustment.reason_key}")

    add_activity_log(
        session,
        user_id=message.from_user.id if message.from_user else None,
        action="distance_calculation",
        details={"distance_km": round(distance_km, 3)},
    )
    await session.commit()
    await state.clear()

    result = i18n.text(
        language,
        "distance.result",
        distance=i18n.text(language, "distance.distance_value", value=f"{distance_km:.2f}"),
        minutes=walking_minutes,
        base_speed=i18n.text(language, "distance.base_speed"),
        weather=weather_text,
        adjustment=adjustment_text,
        advice=advice,
        unavailable_note=i18n.text(language, "distance.weather_unavailable_note") if weather_error else "",
    )
    await message.answer(result, reply_markup=distance_keyboard(i18n, language))


@router.message(DistanceStates.waiting_start, F.text == "/cancel")
@router.message(DistanceStates.waiting_destination, F.text == "/cancel")
async def distance_cancel_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
) -> None:
    await state.clear()
    user = await session.get(User, message.from_user.id)
    if user is None:
        return
    from bot.keyboards.main import main_menu

    await message.answer(
        i18n.text(user.language_code, "common.cancelled"),
        reply_markup=main_menu(i18n, user.language_code),
    )


@router.message(DistanceStates.waiting_start, F.location)
async def start_location_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    language: str,
    weather_service: WeatherService,
) -> None:
    location = message.location
    if location is None:
        return
    await _handle_location(
        latitude=location.latitude,
        longitude=location.longitude,
        message=message,
        state=state,
        session=session,
        i18n=i18n,
        language=language,
        weather_service=weather_service,
    )


@router.message(DistanceStates.waiting_destination, F.location)
async def destination_location_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    language: str,
    weather_service: WeatherService,
) -> None:
    location = message.location
    if location is None:
        return
    await _handle_location(
        latitude=location.latitude,
        longitude=location.longitude,
        message=message,
        state=state,
        session=session,
        i18n=i18n,
        language=language,
        weather_service=weather_service,
    )


@router.message(DistanceStates.waiting_start, F.text)
async def start_coordinate_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    language: str,
    weather_service: WeatherService,
) -> None:
    text = message.text or ""
    try:
        coordinates = parse_coordinates(text)
    except ValueError:
        await message.answer(i18n.text(language, "distance.invalid_coordinates"))
        return
    await _handle_location(
        latitude=coordinates.latitude,
        longitude=coordinates.longitude,
        message=message,
        state=state,
        session=session,
        i18n=i18n,
        language=language,
        weather_service=weather_service,
    )


@router.message(DistanceStates.waiting_destination, F.text)
async def destination_coordinate_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    i18n: I18n,
    language: str,
    weather_service: WeatherService,
) -> None:
    text = message.text or ""
    try:
        coordinates = parse_coordinates(text)
    except ValueError:
        await message.answer(i18n.text(language, "distance.invalid_coordinates"))
        return
    await _handle_location(
        latitude=coordinates.latitude,
        longitude=coordinates.longitude,
        message=message,
        state=state,
        session=session,
        i18n=i18n,
        language=language,
        weather_service=weather_service,
    )


@router.message(DistanceStates.waiting_start)
@router.message(DistanceStates.waiting_destination)
async def invalid_distance_input_handler(message: Message, i18n: I18n, language: str) -> None:
    await message.answer(i18n.text(language, "distance.invalid_input"))
