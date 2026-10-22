{{ config(description='Current-state conformed allergen dimension.') }}

with source_rows as (
    {{ core_source_rows('stg_allergens', 'core_allergens') }}
)

select
    source_rows.allergen_id,
    trim(source_rows.allergen_code) as allergen_code,
    source_rows.allergen_name,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    source_rows._ingested_at as _record_updated_at
from source_rows

