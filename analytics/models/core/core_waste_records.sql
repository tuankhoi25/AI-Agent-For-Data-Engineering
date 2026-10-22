{{ config(description='Waste-record grain. Quantity is positive here; WASTE ledger movements are negative.') }}

with source_rows as (
    {{ core_source_rows('stg_waste_records', 'core_waste_records') }}
)

select
    w.waste_record_id,
    w.branch_id,
    b.branch_code,
    b.branch_name,
    w.stock_item_id,
    si.stock_item_code,
    si.stock_item_name,
    w.inventory_lot_id,
    l.lot_code,
    l.expires_at,
    w.quantity,
    w.uom_id,
    u.uom_code,
    w.reason_code,
    w.recorded_at,
    (w.recorded_at at time zone 'Asia/Ho_Chi_Minh')::date as business_date,
    w.recorded_by,
    w.notes,
    w._created_at,
    w._last_updated_at,
    w._is_deleted,
    w._deleted_at
    {{ core_metadata_columns('w', ['b', 'si', 'l', 'u']) }}
from source_rows w
left join {{ ref('core_branches') }} b
    on w.branch_id = b.branch_id
left join {{ ref('core_stock_items') }} si
    on w.stock_item_id = si.stock_item_id
left join {{ ref('core_inventory_lots') }} l
    on w.inventory_lot_id = l.inventory_lot_id
left join {{ ref('core_units_of_measure') }} u
    on w.uom_id = u.uom_id
