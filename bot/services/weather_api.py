import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
WTTR_URL_TEMPLATE = "https://wttr.in/{location}?format=j1"


@dataclass(frozen=True, slots=True)
class Region:
    id: str
    latitude: float
    longitude: float
    locale_key: str


WEATHER_REGIONS: Sequence[Region] = (
    Region("tashkent", 41.2995, 69.2401, "region.tashkent"),
    Region("samarkand", 39.6542, 66.9597, "region.samarkand"),
    Region("bukhara", 39.7747, 64.4286, "region.bukhara"),
    Region("khorezm", 41.5507, 60.6413, "region.khorezm"),
    Region("fergana", 40.3864, 71.7864, "region.fergana"),
    Region("namangan", 40.9983, 71.6726, "region.namangan"),
    Region("andijan", 40.7821, 72.3442, "region.andijan"),
    Region("kashkadarya", 38.8610, 65.7847, "region.kashkadarya"),
    Region("surkhandarya", 37.2242, 67.2783, "region.surkhandarya"),
    Region("jizzakh", 40.1158, 67.8422, "region.jizzakh"),
    Region("syrdarya", 40.4897, 68.7842, "region.syrdarya"),
    Region("navoiy", 40.0844, 65.3792, "region.navoiy"),
)


@dataclass(frozen=True, slots=True)
class DailyForecast:
    date_local: datetime
    weather_id: int | None
    temperature_min: float | None
    temperature_max: float | None
    humidity: int | None
    wind_speed: float | None


@dataclass(frozen=True, slots=True)
class Forecast:
    region: Region
    timezone_offset_seconds: int
    days: Sequence[DailyForecast]
    source: str


@dataclass(frozen=True, slots=True)
class CurrentWeather:
    temperature_c: float | None
    weather_id: int | None
    source: str


class WeatherServiceError(RuntimeError):
    """Raised for recoverable weather-service failures."""


class WeatherService:
    """Keyless weather service with Open-Meteo primary and wttr.in fallback parsing."""

    def __init__(self, request_timeout: float) -> None:
        self.request_timeout = request_timeout
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _json_request(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._session is None or self._session.closed:
            raise WeatherServiceError("Weather service is not started")
        try:
            async with self._session.get(url, params=params) as response:
                body = await response.text()
                if response.status >= 400:
                    logger.warning("Weather provider returned HTTP %s", response.status)
                    raise WeatherServiceError("Weather provider returned an HTTP error")
                try:
                    payload = await response.json(content_type=None)
                except ValueError as exc:
                    logger.warning("Weather provider returned malformed JSON")
                    raise WeatherServiceError("Weather provider returned malformed JSON") from exc
        except asyncio.TimeoutError as exc:
            raise WeatherServiceError("Weather provider request timed out") from exc
        except aiohttp.ClientError as exc:
            raise WeatherServiceError("Weather provider connection failed") from exc

        if not body.strip() or not isinstance(payload, dict):
            raise WeatherServiceError("Weather provider returned an invalid payload")
        return payload

    async def _open_meteo_request(self, latitude: float, longitude: float) -> dict[str, Any]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "auto",
            "forecast_days": 7,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": (
                "weather_code,temperature_2m_min,temperature_2m_max,"
                "relative_humidity_2m_mean,wind_speed_10m_max"
            ),
        }
        return await self._json_request(OPEN_METEO_URL, params=params)

    async def _wttr_request(self, latitude: float, longitude: float) -> dict[str, Any]:
        location = f"{latitude},{longitude}"
        return await self._json_request(WTTR_URL_TEMPLATE.format(location=location))

    async def get_7_day_forecast(self, region: Region) -> Forecast:
        try:
            payload = await self._open_meteo_request(region.latitude, region.longitude)
            return self._parse_open_meteo_forecast(payload, region)
        except WeatherServiceError:
            logger.warning("Open-Meteo forecast failed for %s; trying wttr.in fallback", region.id)

        try:
            payload = await self._wttr_request(region.latitude, region.longitude)
            return self._parse_wttr_forecast(payload, region)
        except WeatherServiceError as exc:
            logger.warning("All weather forecast providers failed for %s", region.id)
            raise exc

    async def get_current_weather(self, latitude: float, longitude: float) -> CurrentWeather:
        try:
            payload = await self._open_meteo_request(latitude, longitude)
            current = payload.get("current")
            if not isinstance(current, dict):
                raise WeatherServiceError("Open-Meteo current data is missing")
            return CurrentWeather(
                temperature_c=self._as_float(current.get("temperature_2m")),
                weather_id=self._as_int(current.get("weather_code")),
                source="open-meteo",
            )
        except WeatherServiceError:
            logger.warning("Open-Meteo current weather failed; trying wttr.in fallback")

        payload = await self._wttr_request(latitude, longitude)
        current = payload.get("current_condition")
        if not isinstance(current, list) or not current or not isinstance(current[0], dict):
            raise WeatherServiceError("wttr.in current data is missing")
        item = current[0]
        return CurrentWeather(
            temperature_c=self._as_float(item.get("temp_C")),
            weather_id=self._as_int(item.get("weatherCode")),
            source="wttr.in",
        )

    def _parse_open_meteo_forecast(self, payload: dict[str, Any], region: Region) -> Forecast:
        daily = payload.get("daily")
        if not isinstance(daily, dict):
            raise WeatherServiceError("Open-Meteo daily data is missing")

        dates = daily.get("time")
        codes = daily.get("weather_code")
        mins = daily.get("temperature_2m_min")
        maxs = daily.get("temperature_2m_max")
        humidities = daily.get("relative_humidity_2m_mean")
        winds = daily.get("wind_speed_10m_max")
        values = (dates, codes, mins, maxs, humidities, winds)
        if not all(isinstance(value, list) for value in values):
            raise WeatherServiceError("Open-Meteo returned incomplete daily data")
        if len(dates) < 7:
            raise WeatherServiceError("Open-Meteo returned fewer than seven days")

        offset = self._as_int(payload.get("utc_offset_seconds")) or 0
        local_zone = timezone(timedelta(seconds=offset))
        days: list[DailyForecast] = []
        for index in range(7):
            try:
                date_local = datetime.fromisoformat(str(dates[index])).replace(tzinfo=local_zone)
            except (TypeError, ValueError):
                continue
            days.append(
                DailyForecast(
                    date_local=date_local,
                    weather_id=self._as_int(codes[index]),
                    temperature_min=self._as_float(mins[index]),
                    temperature_max=self._as_float(maxs[index]),
                    humidity=self._as_int(humidities[index]),
                    wind_speed=self._as_float(winds[index]),
                )
            )

        if len(days) < 7:
            raise WeatherServiceError("Open-Meteo returned malformed daily dates")
        return Forecast(region=region, timezone_offset_seconds=offset, days=days, source="open-meteo")

    def _parse_wttr_forecast(self, payload: dict[str, Any], region: Region) -> Forecast:
        forecast = payload.get("weather")
        if not isinstance(forecast, list) or len(forecast) < 7:
            raise WeatherServiceError("wttr.in returned fewer than seven days")

        days: list[DailyForecast] = []
        for item in forecast[:7]:
            if not isinstance(item, dict):
                continue
            try:
                date_local = datetime.fromisoformat(str(item.get("date"))).replace(tzinfo=UTC)
            except (TypeError, ValueError):
                continue
            hourly = item.get("hourly") if isinstance(item.get("hourly"), list) else []
            humidity_values: list[int] = []
            wind_values: list[float] = []
            weather_codes: list[int] = []
            for hour in hourly:
                if not isinstance(hour, dict):
                    continue
                humidity = self._as_int(hour.get("humidity"))
                wind = self._as_float(hour.get("windspeedKmph"))
                code = self._as_int(hour.get("weatherCode"))
                if humidity is not None:
                    humidity_values.append(humidity)
                if wind is not None:
                    wind_values.append(wind)
                if code is not None:
                    weather_codes.append(code)
            days.append(
                DailyForecast(
                    date_local=date_local,
                    weather_id=self._select_wttr_code(weather_codes),
                    temperature_min=self._as_float(item.get("mintempC")),
                    temperature_max=self._as_float(item.get("maxtempC")),
                    humidity=round(sum(humidity_values) / len(humidity_values)) if humidity_values else None,
                    wind_speed=max(wind_values) if wind_values else None,
                )
            )

        if len(days) < 7:
            raise WeatherServiceError("wttr.in returned incomplete daily data")
        return Forecast(region=region, timezone_offset_seconds=0, days=days, source="wttr.in")

    @staticmethod
    def _select_wttr_code(codes: list[int]) -> int | None:
        if not codes:
            return None
        # Prefer the most severe precipitation/snow/thunder condition for daily display.
        priority = [399, 395, 392, 389, 386, 359, 356, 353, 350, 317, 314, 311, 308, 305, 302, 299, 296, 293, 266, 263, 248, 260, 200, 122, 119, 116, 113]
        available = set(codes)
        for code in priority:
            if code in available:
                return code
        return codes[0]

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None


def condition_key(weather_id: int | None) -> str:
    if weather_id is None:
        return "unknown"

    # Open-Meteo WMO weather codes.
    if 0 <= weather_id <= 99:
        if weather_id == 0:
            return "clear"
        if weather_id in {1, 2}:
            return "partly_cloudy"
        if weather_id == 3:
            return "cloudy"
        if weather_id in {45, 48}:
            return "atmosphere"
        if weather_id in {51, 53, 55, 56, 57}:
            return "drizzle"
        if weather_id in {61, 63, 65, 66, 67, 80, 81, 82}:
            return "rain"
        if weather_id in {71, 73, 75, 77, 85, 86}:
            return "snow"
        if weather_id in {95, 96, 99}:
            return "thunderstorm"
        return "unknown"

    # wttr.in weather codes.
    wttr_map = {
        113: "clear",
        116: "partly_cloudy",
        119: "cloudy",
        122: "cloudy",
        143: "atmosphere",
        248: "atmosphere",
        260: "atmosphere",
        176: "rain",
        263: "rain",
        266: "rain",
        293: "rain",
        296: "rain",
        299: "rain",
        302: "rain",
        305: "rain",
        308: "rain",
        311: "rain",
        314: "rain",
        317: "rain",
        320: "rain",
        323: "snow",
        326: "snow",
        329: "snow",
        332: "snow",
        335: "snow",
        338: "snow",
        350: "snow",
        353: "rain",
        356: "rain",
        359: "rain",
        362: "snow",
        365: "snow",
        368: "snow",
        371: "snow",
        374: "snow",
        377: "snow",
        386: "thunderstorm",
        389: "thunderstorm",
        392: "snow",
        395: "snow",
    }
    if weather_id in wttr_map:
        return wttr_map[weather_id]

    # Legacy OpenWeather codes are retained for compatibility with previously stored/tested data.
    if 200 <= weather_id <= 232:
        return "thunderstorm"
    if 300 <= weather_id <= 321:
        return "drizzle"
    if 500 <= weather_id <= 531:
        return "rain"
    if 600 <= weather_id <= 622:
        return "snow"
    if 701 <= weather_id <= 781:
        return "atmosphere"
    if weather_id == 800:
        return "clear"
    if weather_id == 801:
        return "partly_cloudy"
    if 802 <= weather_id <= 804:
        return "cloudy"
    return "unknown"
