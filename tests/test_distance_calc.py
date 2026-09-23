from bot.services.distance_calc import (
    BASE_WALKING_SPEED_KMH,
    Coordinates,
    adjusted_walking_speed,
    haversine_distance,
    parse_coordinates,
    walking_time_minutes,
)


def test_parse_coordinates_accepts_spaces() -> None:
    value = parse_coordinates(" 41.2995, 69.2401 ")
    assert value == Coordinates(41.2995, 69.2401)


def test_parse_coordinates_rejects_invalid_ranges() -> None:
    try:
        parse_coordinates("91, 69")
    except ValueError as exc:
        assert str(exc) == "invalid_latitude"
    else:
        raise AssertionError("Expected invalid latitude error")


def test_haversine_zero_distance() -> None:
    point = Coordinates(41.2995, 69.2401)
    assert haversine_distance(point, point) == 0.0


def test_walking_time_rounds_to_minutes() -> None:
    assert walking_time_minutes(5.0, BASE_WALKING_SPEED_KMH) == 60


def test_weather_adjustment_uses_single_severity() -> None:
    speed, adjustment = adjusted_walking_speed(temperature_c=37.0, weather_id=502)
    assert speed == 4.0
    assert adjustment.reason_key == "heavy_rain_snow"


def test_extreme_heat_adjustment() -> None:
    speed, adjustment = adjusted_walking_speed(temperature_c=36.0, weather_id=800)
    assert speed == 4.25
    assert adjustment.reason_key == "extreme_heat"
