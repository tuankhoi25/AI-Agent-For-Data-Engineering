{{ config(
    description='Type 0 calendar dimension for local business dates; calendar attributes are stable and do not require SCD2 history.',
    indexes=[
        {'columns': ['date_sk'], 'unique': true},
        {'columns': ['date_day'], 'unique': true}
    ]
) }}

with event_bounds as (
    select min(business_date) as min_date, max(business_date) as max_date
    from {{ ref('core_sales') }}
    union all
    select min(business_date), max(business_date)
    from {{ ref('core_production_batches') }}
    union all
    select min(business_date), max(business_date)
    from {{ ref('core_waste_records') }}
    union all
    select min(weather_date), max(weather_date)
    from {{ ref('core_weather_daily') }}
    union all
    select min(holiday_date), max(holiday_date)
    from {{ ref('vietnam_holidays') }}
),
bounds as (
    select
        coalesce(min(min_date), (current_timestamp at time zone 'Asia/Ho_Chi_Minh')::date) as min_date,
        greatest(
            coalesce(max(max_date), (current_timestamp at time zone 'Asia/Ho_Chi_Minh')::date),
            (current_timestamp at time zone 'Asia/Ho_Chi_Minh')::date
        ) as max_date
    from event_bounds
),
existing_bounds as (
    {% if is_incremental() %}
        select min(date_day) as min_date, max(date_day) as max_date
        from {{ this }}
    {% else %}
        select null::date as min_date, null::date as max_date
    {% endif %}
),
calendar as (
    select generated_date::date as date_day
    from bounds
    cross join lateral generate_series(bounds.min_date, bounds.max_date, interval '1 day') as dates(generated_date)
),
new_dates as (
    select calendar.date_day
    from calendar
    cross join existing_bounds
    where existing_bounds.min_date is null
       or calendar.date_day < existing_bounds.min_date
       or calendar.date_day > existing_bounds.max_date
)

select
    to_char(new_dates.date_day, 'YYYYMMDD')::integer as date_sk,
    new_dates.date_day,
    extract(isodow from new_dates.date_day)::integer as iso_day_of_week,
    trim(to_char(new_dates.date_day, 'Day')) as day_name,
    extract(day from new_dates.date_day)::integer as day_of_month,
    extract(doy from new_dates.date_day)::integer as day_of_year,
    extract(week from new_dates.date_day)::integer as iso_week_of_year,
    extract(month from new_dates.date_day)::integer as month_number,
    trim(to_char(new_dates.date_day, 'Month')) as month_name,
    extract(quarter from new_dates.date_day)::integer as quarter_number,
    extract(year from new_dates.date_day)::integer as calendar_year,
    date_trunc('month', new_dates.date_day)::date as month_start_date,
    (date_trunc('month', new_dates.date_day) + interval '1 month - 1 day')::date as month_end_date,
    extract(isodow from new_dates.date_day)::integer in (6, 7) as is_weekend,
    case
        when extract(isodow from new_dates.date_day)::integer in (6, 7) then 'WEEKEND'
        else 'WEEKDAY'
    end as day_type,
    coalesce(vietnam_holidays.holiday_name is not null, false) as is_vietnam_holiday,
    vietnam_holidays.holiday_name,
    'Asia/Ho_Chi_Minh'::text as timezone,
    current_timestamp as _record_updated_at
from new_dates
left join {{ ref('vietnam_holidays') }}
    on vietnam_holidays.holiday_date = new_dates.date_day
