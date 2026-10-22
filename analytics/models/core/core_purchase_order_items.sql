{{ config(description='Purchase-order-line grain with expected line value.') }}

with source_rows as (
    {{ core_source_rows('stg_purchase_order_items', 'core_purchase_order_items') }}
)

select
    poi.purchase_order_item_id,
    poi.purchase_order_id,
    po.po_number,
    po.supplier_id,
    po.supplier_code,
    po.supplier_name,
    po.branch_id,
    po.branch_code,
    poi.stock_item_id,
    si.stock_item_code,
    si.stock_item_name,
    poi.ordered_quantity,
    poi.uom_id,
    u.uom_code,
    poi.expected_unit_cost,
    (poi.ordered_quantity * poi.expected_unit_cost)::numeric(38,9) as expected_line_amount,
    po.currency_code,
    po.ordered_at,
    po.expected_at,
    po.status as purchase_order_status,
    poi.notes,
    poi._created_at,
    poi._last_updated_at,
    poi._is_deleted,
    poi._deleted_at
    {{ core_metadata_columns('poi', ['po', 'si', 'u']) }}
from source_rows poi
left join {{ ref('core_purchase_orders') }} po
    on poi.purchase_order_id = po.purchase_order_id
left join {{ ref('core_stock_items') }} si
    on poi.stock_item_id = si.stock_item_id
left join {{ ref('core_units_of_measure') }} u
    on poi.uom_id = u.uom_id
