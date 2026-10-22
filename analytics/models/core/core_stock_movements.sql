{{ config(description='Inventory-ledger grain. Signed quantity_delta is authoritative; no balance is inferred from lot existence.') }}

with source_rows as (
    {{ core_source_rows('stg_stock_movements', 'core_stock_movements') }}
)

select
    sm.stock_movement_id,
    sm.branch_id,
    b.branch_code,
    b.branch_name,
    sm.stock_item_id,
    si.stock_item_code,
    si.stock_item_name,
    si.item_type,
    sm.inventory_lot_id,
    l.lot_code,
    l.expires_at,
    sm.movement_type,
    sm.quantity_delta,
    sm.uom_id,
    u.uom_code,
    sm.unit_cost,
    (sm.quantity_delta * sm.unit_cost)::numeric(38,9) as movement_value,
    sm.occurred_at,
    (sm.occurred_at at time zone 'Asia/Ho_Chi_Minh')::date as business_date,
    sm.source_type,
    sm.source_id,
    sm.idempotency_key,
    sm.created_by,
    sm.notes,
    sm._created_at,
    sm._last_updated_at,
    sm._is_deleted,
    sm._deleted_at
    {{ core_metadata_columns('sm', ['b', 'si', 'l', 'u']) }}
from source_rows sm
left join {{ ref('core_branches') }} b
    on sm.branch_id = b.branch_id
left join {{ ref('core_stock_items') }} si
    on sm.stock_item_id = si.stock_item_id
left join {{ ref('core_inventory_lots') }} l
    on sm.inventory_lot_id = l.inventory_lot_id
left join {{ ref('core_units_of_measure') }} u
    on sm.uom_id = u.uom_id
