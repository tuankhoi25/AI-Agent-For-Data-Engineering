{{ config(
    description='Daily weather fact at location and date grain, linked to the Type 0 date dimension.',
    unique_key=['weather_date', 'location_code', 'weather_source'],
    indexes=[
        {'columns': ['date_sk']},
        {'columns': ['weather_date', 'location_code'], 'unique': true}
    ]
) }}

with changed_rows as (
    select source_rows.*
    from {{ ref('core_weather_daily') }} source_rows
    {% if is_incremental() %}
    where source_rows._source_ingested_at > coalesce(
        (select max(_source_ingested_at) from {{ this }}),
        '1900-01-01'::timestamptz
    )
    {% endif %}
)

select
    date_dimension.date_sk,
    changed_rows.weather_date,
    changed_rows.location_code,
    changed_rows.location_name,
    changed_rows.latitude,
    changed_rows.longitude,
    changed_rows.timezone,
    changed_rows.weather_source,
    changed_rows.weather_model,
    changed_rows.source_url,
    changed_rows.temperature_mean_c,
    changed_rows.temperature_max_c,
    changed_rows.temperature_min_c,
    changed_rows.apparent_temperature_mean_c,
    changed_rows.apparent_temperature_max_c,
    changed_rows.apparent_temperature_min_c,
    changed_rows.relative_humidity_mean_pct,
    changed_rows.relative_humidity_max_pct,
    changed_rows.relative_humidity_min_pct,
    changed_rows.precipitation_sum_mm,
    changed_rows.rain_sum_mm,
    changed_rows.snowfall_sum_cm,
    changed_rows.precipitation_hours,
    changed_rows.weather_code,
    changed_rows.sunrise_at,
    changed_rows.sunset_at,
    changed_rows.daylight_duration_seconds,
    changed_rows.sunshine_duration_seconds,
    changed_rows.wind_speed_max_kmh,
    changed_rows.wind_gusts_max_kmh,
    changed_rows.wind_direction_dominant_deg,
    changed_rows.shortwave_radiation_sum_mj_m2,
    changed_rows.api_fetched_at,
    changed_rows._created_at,
    changed_rows._last_updated_at,
    changed_rows._is_deleted,
    changed_rows._deleted_at,
    changed_rows._source_last_updated_at,
    changed_rows._source_ingested_at,
    changed_rows._record_updated_at
from changed_rows
join {{ ref('dim_date') }} date_dimension
    on date_dimension.date_day = changed_rows.weather_date
