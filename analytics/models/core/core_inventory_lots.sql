{{ config(description='Current-state conformed inventory-lot dimension. A lot record is not itself an on-hand balance.') }}

with source_rows as (
    {{ core_source_rows('stg_inventory_lots', 'core_inventory_lots') }}
)

select
    source_rows.inventory_lot_id,
    source_rows.stock_item_id,
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
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    greatest(source_rows._ingested_at, coalesce(si._record_updated_at, source_rows._ingested_at)) as _record_updated_at
from source_rows
left join {{ ref('core_stock_items') }} si
    on source_rows.stock_item_id = si.stock_item_id

