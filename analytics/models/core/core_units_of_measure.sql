{{ config(description='Current-state conformed units used by purchasing, inventory, recipes and sales.') }}

with source_rows as (
    {{ core_source_rows('stg_units_of_measure', 'core_units_of_measure') }}
)

select
    source_rows.uom_id,
    trim(source_rows.uom_code) as uom_code,
    source_rows.uom_name,
    source_rows.dimension,
    source_rows.is_base_unit,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    source_rows._ingested_at as _record_updated_at
from source_rows
