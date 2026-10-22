#!/usr/bin/env python3
"""Fetch daily Open-Meteo weather and upsert it into bakery.weather_daily."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psycopg


TIMEZONE = "Asia/Ho_Chi_Minh"
LOCATION_CODE = "HCM_BAKERY"
LOCATION_NAME = "TP. Hồ Chí Minh"
LATITUDE = 10.8231
LONGITUDE = 106.6297
ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_SOURCE = "open_meteo_archive"
WEATHER_MODEL = "best_match"
DAILY_VARIABLES = (
    "weather_code",
    "temperature_2m_mean",
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_mean",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "relative_humidity_2m_mean",
    "relative_humidity_2m_max",
    "relative_humidity_2m_min",
    "precipitation_sum",
    "rain_sum",
    "snowfall_sum",
    "precipitation_hours",
    "sunrise",
    "sunset",
    "daylight_duration",
    "sunshine_duration",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
    "shortwave_radiation_sum",
)


def load_dotenv() -> None:
    """Load local .env only when running outside the Dagu container."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("'\"")
        os.environ.setdefault(key.strip(), value)


def dsn_from_environment() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return database_url
    host = os.environ.get("DBT_POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_HOST_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "marmot")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    database = os.environ.get("POSTGRES_DB", "marmot")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def api_url(start_date: date, end_date: date) -> str:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": ",".join(DAILY_VARIABLES),
        "timezone": TIMEZONE,
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    return ENDPOINT + "?" + urlencode(params)


def fetch_daily(start_date: date, end_date: date) -> tuple[dict, str]:
    url = api_url(start_date, end_date)
    request = Request(url, headers={"User-Agent": "MaisonDouceBakeryWeather/1.0"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    if not dates:
        raise RuntimeError("Open-Meteo returned no daily weather rows.")
    return payload, url


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def value(daily: dict, name: str, index: int):
    values = daily.get(name) or []
    return values[index] if index < len(values) else None


def rows_from_payload(payload: dict, source_url: str, fetched_at: datetime) -> list[tuple]:
    daily = payload["daily"]
    result = []
    for index, day_text in enumerate(daily["time"]):
        weather_date = date.fromisoformat(day_text)
        result.append((
            weather_date,
            LOCATION_CODE,
            LOCATION_NAME,
            LATITUDE,
            LONGITUDE,
            TIMEZONE,
            WEATHER_SOURCE,
            WEATHER_MODEL,
            api_url(weather_date, weather_date),
            value(daily, "temperature_2m_mean", index),
            value(daily, "temperature_2m_max", index),
            value(daily, "temperature_2m_min", index),
            value(daily, "apparent_temperature_mean", index),
            value(daily, "apparent_temperature_max", index),
            value(daily, "apparent_temperature_min", index),
            value(daily, "relative_humidity_2m_mean", index),
            value(daily, "relative_humidity_2m_max", index),
            value(daily, "relative_humidity_2m_min", index),
            value(daily, "precipitation_sum", index),
            value(daily, "rain_sum", index),
            value(daily, "snowfall_sum", index),
            value(daily, "precipitation_hours", index),
            value(daily, "weather_code", index),
            parse_timestamp(value(daily, "sunrise", index)),
            parse_timestamp(value(daily, "sunset", index)),
            value(daily, "daylight_duration", index),
            value(daily, "sunshine_duration", index),
            value(daily, "wind_speed_10m_max", index),
            value(daily, "wind_gusts_10m_max", index),
            value(daily, "wind_direction_10m_dominant", index),
            value(daily, "shortwave_radiation_sum", index),
            fetched_at,
        ))
    return result


INSERT_SQL = """
insert into bakery.weather_daily (
    weather_date, location_code, location_name, latitude, longitude, timezone,
    weather_source, weather_model, source_url,
    temperature_mean_c, temperature_max_c, temperature_min_c,
    apparent_temperature_mean_c, apparent_temperature_max_c, apparent_temperature_min_c,
    relative_humidity_mean_pct, relative_humidity_max_pct, relative_humidity_min_pct,
    precipitation_sum_mm, rain_sum_mm, snowfall_sum_cm, precipitation_hours,
    weather_code, sunrise_at, sunset_at, daylight_duration_seconds,
    sunshine_duration_seconds, wind_speed_max_kmh, wind_gusts_max_kmh,
    wind_direction_dominant_deg, shortwave_radiation_sum_mj_m2, api_fetched_at
) values (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
on conflict (weather_date, location_code, weather_source) do update set
    location_name = excluded.location_name,
    latitude = excluded.latitude,
    longitude = excluded.longitude,
    timezone = excluded.timezone,
    weather_model = excluded.weather_model,
    source_url = excluded.source_url,
    temperature_mean_c = excluded.temperature_mean_c,
    temperature_max_c = excluded.temperature_max_c,
    temperature_min_c = excluded.temperature_min_c,
    apparent_temperature_mean_c = excluded.apparent_temperature_mean_c,
    apparent_temperature_max_c = excluded.apparent_temperature_max_c,
    apparent_temperature_min_c = excluded.apparent_temperature_min_c,
    relative_humidity_mean_pct = excluded.relative_humidity_mean_pct,
    relative_humidity_max_pct = excluded.relative_humidity_max_pct,
    relative_humidity_min_pct = excluded.relative_humidity_min_pct,
    precipitation_sum_mm = excluded.precipitation_sum_mm,
    rain_sum_mm = excluded.rain_sum_mm,
    snowfall_sum_cm = excluded.snowfall_sum_cm,
    precipitation_hours = excluded.precipitation_hours,
    weather_code = excluded.weather_code,
    sunrise_at = excluded.sunrise_at,
    sunset_at = excluded.sunset_at,
    daylight_duration_seconds = excluded.daylight_duration_seconds,
    sunshine_duration_seconds = excluded.sunshine_duration_seconds,
    wind_speed_max_kmh = excluded.wind_speed_max_kmh,
    wind_gusts_max_kmh = excluded.wind_gusts_max_kmh,
    wind_direction_dominant_deg = excluded.wind_direction_dominant_deg,
    shortwave_radiation_sum_mj_m2 = excluded.shortwave_radiation_sum_mj_m2,
    api_fetched_at = excluded.api_fetched_at,
    _is_deleted = false
where (weather_daily.location_name,
       weather_daily.latitude,
       weather_daily.longitude,
       weather_daily.timezone,
       weather_daily.weather_model,
       weather_daily.source_url,
       weather_daily.temperature_mean_c,
       weather_daily.temperature_max_c,
       weather_daily.temperature_min_c,
       weather_daily.apparent_temperature_mean_c,
       weather_daily.apparent_temperature_max_c,
       weather_daily.apparent_temperature_min_c,
       weather_daily.relative_humidity_mean_pct,
       weather_daily.relative_humidity_max_pct,
       weather_daily.relative_humidity_min_pct,
       weather_daily.precipitation_sum_mm,
       weather_daily.rain_sum_mm,
       weather_daily.snowfall_sum_cm,
       weather_daily.precipitation_hours,
       weather_daily.weather_code,
       weather_daily.sunrise_at,
       weather_daily.sunset_at,
       weather_daily.daylight_duration_seconds,
       weather_daily.sunshine_duration_seconds,
       weather_daily.wind_speed_max_kmh,
       weather_daily.wind_gusts_max_kmh,
       weather_daily.wind_direction_dominant_deg,
       weather_daily.shortwave_radiation_sum_mj_m2,
       weather_daily._is_deleted)
  is distinct from
      (excluded.location_name,
       excluded.latitude,
       excluded.longitude,
       excluded.timezone,
       excluded.weather_model,
       excluded.source_url,
       excluded.temperature_mean_c,
       excluded.temperature_max_c,
       excluded.temperature_min_c,
       excluded.apparent_temperature_mean_c,
       excluded.apparent_temperature_max_c,
       excluded.apparent_temperature_min_c,
       excluded.relative_humidity_mean_pct,
       excluded.relative_humidity_max_pct,
       excluded.relative_humidity_min_pct,
       excluded.precipitation_sum_mm,
       excluded.rain_sum_mm,
       excluded.snowfall_sum_cm,
       excluded.precipitation_hours,
       excluded.weather_code,
       excluded.sunrise_at,
       excluded.sunset_at,
       excluded.daylight_duration_seconds,
       excluded.sunshine_duration_seconds,
       excluded.wind_speed_max_kmh,
       excluded.wind_gusts_max_kmh,
       excluded.wind_direction_dominant_deg,
       excluded.shortwave_radiation_sum_mj_m2,
       false)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Number of completed local days to refresh.")
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    args = parser.parse_args()
    load_dotenv()
    today = datetime.now().astimezone().date()
    end_date = args.end_date or (today - timedelta(days=1))
    start_date = args.start_date or (end_date - timedelta(days=max(args.days, 1) - 1))
    if start_date > end_date:
        raise SystemExit("start date must be on or before end date")

    payload, source_url = fetch_daily(start_date, end_date)
    rows = rows_from_payload(payload, source_url, datetime.now().astimezone())
    expected_days = (end_date - start_date).days + 1
    if len(rows) != expected_days:
        raise RuntimeError(f"Expected {expected_days} daily rows, received {len(rows)}.")
    with psycopg.connect(dsn_from_environment()) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(INSERT_SQL, rows)
    print(f"Weather upsert complete: {len(rows)} rows, {start_date} through {end_date}.")
    print(f"Source: {source_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
