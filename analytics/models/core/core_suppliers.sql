{{ config(description='Current-state conformed supplier dimension.') }}

with source_rows as (
    {{ core_source_rows('stg_suppliers', 'core_suppliers') }}
)

select
    source_rows.supplier_id,
    trim(source_rows.supplier_code) as supplier_code,
    source_rows.supplier_name,
    source_rows.supplier_type,
    trim(source_rows.country_code) as country_code,
    source_rows.website,
    source_rows.phone,
    source_rows.email,
    source_rows.address,
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

