{{ config(description='Append-only staging history of daily Open-Meteo weather observations.') }}

{{ source_incremental('bakery', 'weather_daily') }}
