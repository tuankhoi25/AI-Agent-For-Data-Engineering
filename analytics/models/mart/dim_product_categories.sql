{{ config(
    description='SCD2 product-category dimension with a durable surrogate key.',
    pre_hook="{{ ensure_scd2_sequence() }}"
) }}

with source_rows as (
    {{ scd2_dimension_rows('snap_dim_product_categories', 'category_sk', 'category_id') }}
)

select
    source_rows.category_sk,
    source_rows.dbt_scd_id as _dimension_version_id,
    source_rows.category_id,
    trim(source_rows.category_code) as category_code,
    source_rows.category_name,
    source_rows.parent_category_id,
    source_rows.description,
    source_rows.is_active,
    source_rows._effective_valid_from as _valid_from,
    source_rows.dbt_valid_from as _observed_from,
    source_rows.dbt_valid_to as _valid_to,
    source_rows.dbt_valid_to is null as _is_current,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    greatest(source_rows._source_last_updated_at, coalesce(source_rows.dbt_updated_at, source_rows._source_last_updated_at)) as _record_updated_at
from source_rows

