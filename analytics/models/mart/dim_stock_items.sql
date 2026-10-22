{{ config(
    description='SCD2 inventory-item dimension with a historical base-unit reference.',
    pre_hook="{{ ensure_scd2_sequence() }}"
) }}

with source_rows as (
    {{ scd2_dimension_rows('snap_dim_stock_items', 'stock_item_sk', 'stock_item_id') }}
)

select
    source_rows.stock_item_sk,
    source_rows.dbt_scd_id as _dimension_version_id,
    source_rows.stock_item_id,
    trim(source_rows.stock_item_code) as stock_item_code,
    source_rows.stock_item_name,
    source_rows.item_type,
    source_rows.base_uom_id,
    u.uom_sk as base_uom_sk,
    u.uom_code as base_uom_code,
    u.dimension as base_uom_dimension,
    source_rows.track_lot,
    source_rows.track_expiry,
    source_rows.reorder_level,
    source_rows.is_active,
    source_rows.notes,
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
left join {{ ref('dim_units_of_measure') }} u
    on source_rows.base_uom_id = u.uom_id
   and source_rows._effective_valid_from >= u._valid_from
   and source_rows._effective_valid_from < coalesce(u._valid_to, '9999-12-31'::timestamptz)

