{{ config(description='Current-state conformed inventory-item dimension with base-unit and lot/expiry policy.') }}

with source_rows as (
    {{ core_source_rows('stg_stock_items', 'core_stock_items') }}
)

select
    source_rows.stock_item_id,
    trim(source_rows.stock_item_code) as stock_item_code,
    source_rows.stock_item_name,
    source_rows.item_type,
    source_rows.base_uom_id,
    u.uom_code as base_uom_code,
    u.dimension as base_uom_dimension,
    source_rows.track_lot,
    source_rows.track_expiry,
    source_rows.reorder_level,
    source_rows.is_active,
    source_rows.notes,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    greatest(source_rows._ingested_at, coalesce(u._record_updated_at, source_rows._ingested_at)) as _record_updated_at
from source_rows
left join {{ ref('core_units_of_measure') }} u
    on source_rows.base_uom_id = u.uom_id

