{{ config(description='Current-state conformed promotion dimension. Configured discount value is distinct from actual applied discount.') }}

with source_rows as (
    {{ core_source_rows('stg_promotions', 'core_promotions') }}
)

select
    source_rows.promotion_id,
    trim(source_rows.promotion_code) as promotion_code,
    source_rows.promotion_name,
    source_rows.promotion_type,
    source_rows.discount_value,
    source_rows.minimum_order_amount,
    source_rows.starts_at,
    source_rows.ends_at,
    source_rows.max_uses,
    source_rows.is_active,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    source_rows._ingested_at as _record_updated_at
from source_rows

