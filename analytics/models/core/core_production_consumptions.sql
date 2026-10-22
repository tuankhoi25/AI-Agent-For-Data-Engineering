{{ config(description='Production-consumption grain. quantity_used is positive detail; stock ledger records the negative movement separately.') }}

with source_rows as (
    {{ core_source_rows('stg_production_consumptions', 'core_production_consumptions') }}
)

select
    pc.production_consumption_id,
    pc.production_batch_id,
    pb.batch_number,
    pb.branch_id,
    pb.branch_code,
    pb.product_id,
    pb.sku as output_sku,
    pb.product_name as output_product_name,
    pc.stock_item_id,
    si.stock_item_code,
    si.stock_item_name,
    pc.inventory_lot_id,
    l.lot_code,
    pc.quantity_used,
    pc.uom_id,
    u.uom_code,
    pc.unit_cost,
    (pc.quantity_used * pc.unit_cost)::numeric(38,9) as consumption_value,
    pc.notes,
    pc._created_at,
    pc._last_updated_at,
    pc._is_deleted,
    pc._deleted_at
    {{ core_metadata_columns('pc', ['pb', 'si', 'l', 'u']) }}
from source_rows pc
left join {{ ref('core_production_batches') }} pb
    on pc.production_batch_id = pb.production_batch_id
left join {{ ref('core_stock_items') }} si
    on pc.stock_item_id = si.stock_item_id
left join {{ ref('core_inventory_lots') }} l
    on pc.inventory_lot_id = l.inventory_lot_id
left join {{ ref('core_units_of_measure') }} u
    on pc.uom_id = u.uom_id
