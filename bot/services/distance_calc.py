from dataclasses import dataclass
from math import asin, atan2, cos, isfinite, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0
BASE_WALKING_SPEED_KMH = 5.0
HEAVY_RAIN_SPEED_MULTIPLIER = 0.80
EXTREME_TEMPERATURE_SPEED_MULTIPLIER = 0.85
EXTREME_HEAT_THRESHOLD_C = 35.0
EXTREME_COLD_THRESHOLD_C = 0.0


@dataclass(frozen=True, slots=True)
class Coordinates:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class WeatherAdjustment:
    multiplier: float
    reason_key: str


def parse_coordinates(text: str) -> Coordinates:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 2 or not all(parts):
        raise ValueError("invalid_coordinates")
    try:
        latitude = float(parts[0])
        longitude = float(parts[1])
    except ValueError as exc:
        raise ValueError("invalid_coordinates") from exc
    if not isfinite(latitude) or not isfinite(longitude):
        raise ValueError("invalid_coordinates")
    if not -90.0 <= latitude <= 90.0:
        raise ValueError("invalid_latitude")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("invalid_longitude")
    return Coordinates(latitude=latitude, longitude=longitude)


def haversine_distance(start: Coordinates, destination: Coordinates) -> float:
    latitude_1 = radians(start.latitude)
    longitude_1 = radians(start.longitude)
    latitude_2 = radians(destination.latitude)
    longitude_2 = radians(destination.longitude)
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = longitude_2 - longitude_1

    a = (
        sin(delta_latitude / 2.0) ** 2
        + cos(latitude_1) * cos(latitude_2) * sin(delta_longitude / 2.0) ** 2
    )
    a = min(1.0, max(0.0, a))
    c = 2.0 * atan2(sqrt(a), sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


def is_heavy_rain_or_snow(weather_id: int | None) -> bool:
    if weather_id is None:
        return False

    # Open-Meteo WMO codes. These include rain showers, heavy rain, snow,
    # and freezing precipitation that should trigger the single 20% slowdown.
    wmo_severe = {55, 57, 65, 67, 75, 77, 82, 86, 95, 96, 99}
    if 0 <= weather_id <= 99:
        return weather_id in wmo_severe

    # wttr.in / legacy OpenWeather compatibility codes.
    heavy_rain_ids = {302, 305, 308, 311, 314, 317, 320, 356, 359, 386, 389}
    snow_ids = set(range(323, 339)) | {350, 362, 365, 368, 371, 374, 377, 392, 395}
    legacy_openweather_rain = {502, 503, 504, 522, 531}
    legacy_openweather_snow = set(range(600, 623))
    return (
        weather_id in heavy_rain_ids
        or weather_id in snow_ids
        or weather_id in legacy_openweather_rain
        or weather_id in legacy_openweather_snow
    )


def calculate_weather_adjustment(
    *,
    temperature_c: float | None,
    weather_id: int | None,
) -> WeatherAdjustment:
    if is_heavy_rain_or_snow(weather_id):
        return WeatherAdjustment(HEAVY_RAIN_SPEED_MULTIPLIER, "heavy_rain_snow")
    if temperature_c is not None and temperature_c > EXTREME_HEAT_THRESHOLD_C:
        return WeatherAdjustment(EXTREME_TEMPERATURE_SPEED_MULTIPLIER, "extreme_heat")
    if temperature_c is not None and temperature_c < EXTREME_COLD_THRESHOLD_C:
        return WeatherAdjustment(EXTREME_TEMPERATURE_SPEED_MULTIPLIER, "extreme_cold")
    return WeatherAdjustment(1.0, "normal")


def walking_time_minutes(distance_km: float, speed_kmh: float) -> int:
    if distance_km <= 0.0:
        return 0
    if speed_kmh <= 0.0:
        raise ValueError("speed must be positive")
    minutes = distance_km / speed_kmh * 60.0
    return max(1, round(minutes))


def adjusted_walking_speed(
    *,
    temperature_c: float | None,
    weather_id: int | None,
) -> tuple[float, WeatherAdjustment]:
    adjustment = calculate_weather_adjustment(
        temperature_c=temperature_c,
        weather_id=weather_id,
    )
    return BASE_WALKING_SPEED_KMH * adjustment.multiplier, adjustment
