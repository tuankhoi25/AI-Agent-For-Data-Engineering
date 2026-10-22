{{ config(
    description='SCD2 inventory-lot dimension. A lot record is not itself an on-hand balance.',
    pre_hook="{{ ensure_scd2_sequence() }}"
) }}

with source_rows as (
    {{ scd2_dimension_rows('snap_dim_inventory_lots', 'inventory_lot_sk', 'inventory_lot_id') }}
)

select
    source_rows.inventory_lot_sk,
    source_rows.dbt_scd_id as _dimension_version_id,
    source_rows.inventory_lot_id,
    source_rows.stock_item_id,
    si.stock_item_sk,
    si.stock_item_code,
    si.stock_item_name,
    source_rows.lot_code,
    source_rows.supplier_lot_code,
    source_rows.goods_receipt_id,
    source_rows.manufactured_at,
    source_rows.received_at,
    source_rows.expires_at,
    source_rows.unit_cost,
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
left join {{ ref('dim_stock_items') }} si
    on source_rows.stock_item_id = si.stock_item_id
   and source_rows._effective_valid_from >= si._valid_from
   and source_rows._effective_valid_from < coalesce(si._valid_to, '9999-12-31'::timestamptz)

