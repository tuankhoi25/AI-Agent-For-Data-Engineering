{{ config(description='Latest conformed daily weather observation per location and source.') }}

with source_rows as (
    {{ core_source_rows('stg_weather_daily', 'core_weather_daily') }}
)

select
    source_rows.weather_daily_id,
    source_rows.weather_date,
    source_rows.location_code,
    source_rows.location_name,
    source_rows.latitude,
    source_rows.longitude,
    source_rows.timezone,
    source_rows.weather_source,
    source_rows.weather_model,
    source_rows.source_url,
    source_rows.temperature_mean_c,
    source_rows.temperature_max_c,
    source_rows.temperature_min_c,
    source_rows.apparent_temperature_mean_c,
    source_rows.apparent_temperature_max_c,
    source_rows.apparent_temperature_min_c,
    source_rows.relative_humidity_mean_pct,
    source_rows.relative_humidity_max_pct,
    source_rows.relative_humidity_min_pct,
    source_rows.precipitation_sum_mm,
    source_rows.rain_sum_mm,
    source_rows.snowfall_sum_cm,
    source_rows.precipitation_hours,
    source_rows.weather_code,
    source_rows.sunrise_at,
    source_rows.sunset_at,
    source_rows.daylight_duration_seconds,
    source_rows.sunshine_duration_seconds,
    source_rows.wind_speed_max_kmh,
    source_rows.wind_gusts_max_kmh,
    source_rows.wind_direction_dominant_deg,
    source_rows.shortwave_radiation_sum_mj_m2,
    source_rows.api_fetched_at,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    source_rows._ingested_at as _record_updated_at
from source_rows
