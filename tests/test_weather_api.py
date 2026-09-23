from datetime import timezone

from bot.services.weather_api import Region, WeatherService, condition_key


def _open_meteo_payload() -> dict:
    return {
        "latitude": 41.3,
        "longitude": 69.24,
        "timezone": "Asia/Tashkent",
        "utc_offset_seconds": 18000,
        "daily": {
            "time": [
                "2026-09-23",
                "2026-09-24",
                "2026-09-25",
                "2026-09-26",
                "2026-09-27",
                "2026-09-28",
                "2026-09-29",
            ],
            "weather_code": [0, 2, 3, 61, 65, 71, 95],
            "temperature_2m_min": [15, 16, 17, 18, 19, 20, 21],
            "temperature_2m_max": [30, 31, 32, 29, 28, 27, 26],
            "relative_humidity_2m_mean": [40, 41, 42, 60, 70, 65, 55],
            "wind_speed_10m_max": [10, 11, 12, 13, 14, 15, 16],
        },
    }


def _wttr_payload() -> dict:
    return {
        "weather": [
            {
                "date": "2026-09-23",
                "mintempC": "15",
                "maxtempC": "30",
                "hourly": [
                    {"humidity": "40", "windspeedKmph": "10", "weatherCode": "113"},
                    {"humidity": "60", "windspeedKmph": "20", "weatherCode": "302"},
                ],
            }
        ] * 7
    }


def test_open_meteo_parser_returns_seven_days() -> None:
    service = WeatherService(15.0)
    region = Region("tashkent", 41.2995, 69.2401, "region.tashkent")
    forecast = service._parse_open_meteo_forecast(_open_meteo_payload(), region)

    assert len(forecast.days) == 7
    assert forecast.source == "open-meteo"
    assert forecast.days[0].temperature_min == 15.0
    assert forecast.days[4].weather_id == 65
    assert forecast.days[0].date_local.utcoffset().total_seconds() == 18000


def test_wttr_parser_uses_parsed_hourly_humidity_and_max_wind() -> None:
    service = WeatherService(15.0)
    region = Region("tashkent", 41.2995, 69.2401, "region.tashkent")
    forecast = service._parse_wttr_forecast(_wttr_payload(), region)

    assert len(forecast.days) == 7
    assert forecast.source == "wttr.in"
    assert forecast.days[0].humidity == 50
    assert forecast.days[0].wind_speed == 20.0
    assert forecast.days[0].weather_id == 302
    assert forecast.days[0].date_local.tzinfo == timezone.utc


def test_condition_key_supports_open_meteo_wmo_codes() -> None:
    assert condition_key(0) == "clear"
    assert condition_key(2) == "partly_cloudy"
    assert condition_key(3) == "cloudy"
    assert condition_key(65) == "rain"
    assert condition_key(75) == "snow"
    assert condition_key(95) == "thunderstorm"


def test_condition_key_supports_wttr_codes() -> None:
    assert condition_key(113) == "clear"
    assert condition_key(119) == "cloudy"
    assert condition_key(302) == "rain"
    assert condition_key(386) == "thunderstorm"


def _met_norway_payload() -> dict:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    timeseries = []
    for day in range(8):
        for hour in (0, 6, 12, 18):
            instant = now + timedelta(days=day, hours=hour)
            timeseries.append(
                {
                    "time": instant.isoformat().replace("+00:00", "Z"),
                    "data": {
                        "instant": {
                            "details": {
                                "air_temperature": 20 + day,
                                "relative_humidity": 50 + day,
                                "wind_speed": 2 + day,
                            }
                        },
                        "next_1_hours": {
                            "summary": {"symbol_code": "clearsky_day" if day % 2 == 0 else "rain_day"}
                        },
                    },
                }
            )
    return {"properties": {"timeseries": timeseries}}


def test_met_norway_parser_returns_seven_days() -> None:
    service = WeatherService(15.0)
    region = Region("tashkent", 41.2995, 69.2401, "region.tashkent")
    forecast = service._parse_met_norway_forecast(_met_norway_payload(), region)

    assert len(forecast.days) == 7
    assert forecast.source == "met.no"
    assert forecast.days[0].temperature_min == 20.0
    assert forecast.days[0].temperature_max == 20.0
    assert forecast.days[1].weather_id == 63
    assert forecast.days[0].date_local.utcoffset().total_seconds() == 18000


def test_met_symbol_mapping() -> None:
    assert WeatherService._met_symbol_to_wmo("clearsky_day") == 0
    assert WeatherService._met_symbol_to_wmo("partlycloudy_day") == 2
    assert WeatherService._met_symbol_to_wmo("rain_day") == 63
    assert WeatherService._met_symbol_to_wmo("heavysnowandthunder_night") == 95
