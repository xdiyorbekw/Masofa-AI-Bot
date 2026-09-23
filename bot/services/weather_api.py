import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MET_NORWAY_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
WTTR_URL_TEMPLATE = "https://wttr.in/{location}?format=j1"

# MET Norway requires a descriptive, unique User-Agent. It has global coverage
# and returns forecasts for up to nine days, so it is a better long-range
# fallback than wttr.in for this bot.
MET_USER_AGENT = "MasofaAI/1.0 (https://t.me/masofai_bot)"
UZBEKISTAN_TZ_OFFSET_SECONDS = 5 * 60 * 60
FORECAST_CACHE_TTL_SECONDS = 15 * 60
CURRENT_CACHE_TTL_SECONDS = 5 * 60


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
        self._forecast_cache: dict[str, tuple[float, Forecast]] = {}
        self._current_cache: dict[tuple[float, float], tuple[float, CurrentWeather]] = {}
        self._forecast_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _json_request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if self._session is None or self._session.closed:
            raise WeatherServiceError("Weather service is not started")
        try:
            async with self._session.get(url, params=params, headers=headers) as response:
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

    async def _met_norway_request(self, latitude: float, longitude: float) -> dict[str, Any]:
        # MET Norway asks clients to identify themselves and recommends no more
        # than four decimal places to improve server-side caching.
        params = {
            "lat": f"{latitude:.4f}",
            "lon": f"{longitude:.4f}",
        }
        return await self._json_request(
            MET_NORWAY_URL,
            params=params,
            headers={"User-Agent": MET_USER_AGENT, "Accept": "application/json"},
        )

    async def _wttr_request(self, latitude: float, longitude: float) -> dict[str, Any]:
        location = f"{latitude},{longitude}"
        return await self._json_request(WTTR_URL_TEMPLATE.format(location=location))

    async def get_7_day_forecast(self, region: Region) -> Forecast:
        cached = self._forecast_cache.get(region.id)
        if cached and time.monotonic() - cached[0] < FORECAST_CACHE_TTL_SECONDS:
            return cached[1]

        async with self._forecast_lock:
            # Another request may have filled the cache while we waited.
            cached = self._forecast_cache.get(region.id)
            if cached and time.monotonic() - cached[0] < FORECAST_CACHE_TTL_SECONDS:
                return cached[1]

            try:
                payload = await self._open_meteo_request(region.latitude, region.longitude)
                forecast = self._parse_open_meteo_forecast(payload, region)
                self._forecast_cache[region.id] = (time.monotonic(), forecast)
                return forecast
            except WeatherServiceError as exc:
                logger.warning(
                    "Open-Meteo forecast failed for %s: %s; trying MET Norway",
                    region.id,
                    exc,
                )

            try:
                payload = await self._met_norway_request(region.latitude, region.longitude)
                forecast = self._parse_met_norway_forecast(payload, region)
                self._forecast_cache[region.id] = (time.monotonic(), forecast)
                return forecast
            except WeatherServiceError as exc:
                logger.warning(
                    "MET Norway forecast failed for %s: %s; trying wttr.in",
                    region.id,
                    exc,
                )

            try:
                payload = await self._wttr_request(region.latitude, region.longitude)
                forecast = self._parse_wttr_forecast(payload, region)
                self._forecast_cache[region.id] = (time.monotonic(), forecast)
                return forecast
            except WeatherServiceError as exc:
                # If all providers are temporarily unavailable, an older
                # successful response is still more useful than an error.
                stale = self._forecast_cache.get(region.id)
                if stale:
                    logger.warning(
                        "All weather providers failed for %s; serving stale cached forecast",
                        region.id,
                    )
                    return stale[1]
                logger.warning("All weather forecast providers failed for %s: %s", region.id, exc)
                raise exc

    async def get_current_weather(self, latitude: float, longitude: float) -> CurrentWeather:
        cache_key = (round(latitude, 4), round(longitude, 4))
        cached = self._current_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < CURRENT_CACHE_TTL_SECONDS:
            return cached[1]

        try:
            payload = await self._open_meteo_request(latitude, longitude)
            current = payload.get("current")
            if not isinstance(current, dict):
                raise WeatherServiceError("Open-Meteo current data is missing")
            result = CurrentWeather(
                temperature_c=self._as_float(current.get("temperature_2m")),
                weather_id=self._as_int(current.get("weather_code")),
                source="open-meteo",
            )
            self._current_cache[cache_key] = (time.monotonic(), result)
            return result
        except WeatherServiceError as exc:
            logger.warning("Open-Meteo current weather failed: %s; trying MET Norway", exc)

        try:
            payload = await self._met_norway_request(latitude, longitude)
            result = self._parse_met_norway_current(payload)
            self._current_cache[cache_key] = (time.monotonic(), result)
            return result
        except WeatherServiceError as exc:
            logger.warning("MET Norway current weather failed: %s; trying wttr.in", exc)

        payload = await self._wttr_request(latitude, longitude)
        current = payload.get("current_condition")
        if not isinstance(current, list) or not current or not isinstance(current[0], dict):
            raise WeatherServiceError("wttr.in current data is missing")
        item = current[0]
        result = CurrentWeather(
            temperature_c=self._as_float(item.get("temp_C")),
            weather_id=self._as_int(item.get("weatherCode")),
            source="wttr.in",
        )
        self._current_cache[cache_key] = (time.monotonic(), result)
        return result

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

    def _parse_met_norway_current(self, payload: dict[str, Any]) -> CurrentWeather:
        timeseries = self._met_timeseries(payload)
        if not timeseries:
            raise WeatherServiceError("MET Norway returned no timeseries")

        first = timeseries[0]
        details = (
            first.get("data", {}).get("instant", {}).get("details", {})
            if isinstance(first.get("data"), dict)
            else {}
        )
        if not isinstance(details, dict):
            raise WeatherServiceError("MET Norway current data is missing")

        symbol = self._met_symbol(first)
        return CurrentWeather(
            temperature_c=self._as_float(details.get("air_temperature")),
            weather_id=self._met_symbol_to_wmo(symbol),
            source="met.no",
        )

    def _parse_met_norway_forecast(self, payload: dict[str, Any], region: Region) -> Forecast:
        timeseries = self._met_timeseries(payload)
        if not timeseries:
            raise WeatherServiceError("MET Norway returned no timeseries")

        local_zone = timezone(timedelta(seconds=UZBEKISTAN_TZ_OFFSET_SECONDS))
        today = datetime.now(local_zone).date()
        grouped: dict[Any, list[dict[str, Any]]] = {}

        for item in timeseries:
            if not isinstance(item, dict):
                continue
            raw_time = item.get("time")
            try:
                instant = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            local_dt = instant.astimezone(local_zone)
            day = local_dt.date()
            if day < today:
                continue
            grouped.setdefault(day, []).append(item)

        days: list[DailyForecast] = []
        for day in sorted(grouped)[:7]:
            items = grouped[day]
            temperatures: list[float] = []
            humidities: list[int] = []
            winds: list[float] = []
            weather_ids: list[int] = []

            for item in items:
                data = item.get("data") if isinstance(item.get("data"), dict) else {}
                instant = data.get("instant") if isinstance(data.get("instant"), dict) else {}
                details = instant.get("details") if isinstance(instant.get("details"), dict) else {}

                temp = self._as_float(details.get("air_temperature"))
                humidity = self._as_int(details.get("relative_humidity"))
                wind = self._as_float(details.get("wind_speed"))
                if temp is not None:
                    temperatures.append(temp)
                if humidity is not None:
                    humidities.append(humidity)
                if wind is not None:
                    winds.append(wind)

                code = self._met_symbol_to_wmo(self._met_symbol(item))
                if code is not None:
                    weather_ids.append(code)

            if not temperatures:
                continue

            # Prefer the most severe symbol seen during the day.
            weather_id = self._select_met_code(weather_ids)
            date_local = datetime.combine(day, datetime.min.time(), tzinfo=local_zone)
            days.append(
                DailyForecast(
                    date_local=date_local,
                    weather_id=weather_id,
                    temperature_min=min(temperatures),
                    temperature_max=max(temperatures),
                    humidity=round(sum(humidities) / len(humidities)) if humidities else None,
                    wind_speed=max(winds) if winds else None,
                )
            )

        if len(days) < 7:
            raise WeatherServiceError(f"MET Norway returned only {len(days)} forecast days")

        return Forecast(
            region=region,
            timezone_offset_seconds=UZBEKISTAN_TZ_OFFSET_SECONDS,
            days=days,
            source="met.no",
        )

    @staticmethod
    def _met_timeseries(payload: dict[str, Any]) -> list[dict[str, Any]]:
        properties = payload.get("properties")
        if not isinstance(properties, dict):
            return []
        timeseries = properties.get("timeseries")
        if not isinstance(timeseries, list):
            return []
        return [item for item in timeseries if isinstance(item, dict)]

    @staticmethod
    def _met_symbol(item: dict[str, Any]) -> str | None:
        data = item.get("data")
        if not isinstance(data, dict):
            return None
        for period in ("next_1_hours", "next_6_hours", "next_12_hours"):
            block = data.get(period)
            if not isinstance(block, dict):
                continue
            summary = block.get("summary")
            if isinstance(summary, dict):
                symbol = summary.get("symbol_code")
                if isinstance(symbol, str):
                    return symbol
        return None

    @staticmethod
    def _met_symbol_to_wmo(symbol: str | None) -> int | None:
        if not symbol:
            return None
        base = symbol.lower().split("_")[0]
        mapping = {
            "clearsky": 0,
            "fair": 1,
            "partlycloudy": 2,
            "cloudy": 3,
            "fog": 45,
            "lightrain": 61,
            "rain": 63,
            "heavyrain": 65,
            "lightrainshowers": 61,
            "rainshowers": 63,
            "heavyrainshowers": 65,
            "lightsleet": 66,
            "sleet": 67,
            "heavysleet": 67,
            "lightsnow": 71,
            "snow": 73,
            "heavysnow": 75,
            "lightsnowshowers": 71,
            "snowshowers": 73,
            "heavysnowshowers": 75,
            "rainandsnow": 67,
            "lightrainandthunder": 95,
            "rainandthunder": 95,
            "heavyrainandthunder": 95,
            "lightsnowandthunder": 95,
            "snowandthunder": 95,
            "heavysnowandthunder": 95,
        }
        return mapping.get(base)

    @staticmethod
    def _select_met_code(codes: list[int]) -> int | None:
        if not codes:
            return None
        priority = [95, 75, 73, 71, 67, 65, 63, 61, 45, 3, 2, 1, 0]
        available = set(codes)
        for code in priority:
            if code in available:
                return code
        return codes[0]

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
