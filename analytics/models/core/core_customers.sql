{{ config(description='Current-state conformed customer dimension; a profile may have zero purchases.') }}

with source_rows as (
    {{ core_source_rows('stg_customers', 'core_customers') }}
)

select
    source_rows.customer_id,
    nullif(trim(source_rows.customer_code), '') as customer_code,
    source_rows.full_name,
    source_rows.phone,
    lower(nullif(trim(source_rows.email), '')) as email,
    source_rows.date_of_birth,
    source_rows.joined_at,
    source_rows.marketing_consent,
    source_rows.is_active,
    source_rows.notes,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    source_rows._ingested_at as _record_updated_at
from source_rows

