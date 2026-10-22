{{ config(description='Current-state conformed product-category hierarchy.') }}

with source_rows as (
    {{ core_source_rows('stg_product_categories', 'core_product_categories') }}
)

select
    source_rows.category_id,
    trim(source_rows.category_code) as category_code,
    source_rows.category_name,
    source_rows.parent_category_id,
    source_rows.description,
    source_rows.is_active,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    source_rows._ingested_at as _record_updated_at
from source_rows

