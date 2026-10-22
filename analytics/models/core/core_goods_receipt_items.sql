{{ config(description='Goods-receipt-line grain with actual received value.') }}

with source_rows as (
    {{ core_source_rows('stg_goods_receipt_items', 'core_goods_receipt_items') }}
)

select
    gri.goods_receipt_item_id,
    gri.goods_receipt_id,
    gr.receipt_number,
    gri.purchase_order_item_id,
    poi.po_number,
    gr.purchase_order_id,
    gr.supplier_id,
    gr.supplier_code,
    gr.supplier_name,
    gr.branch_id,
    gr.branch_code,
    gri.stock_item_id,
    si.stock_item_code,
    si.stock_item_name,
    gri.inventory_lot_id,
    gri.received_quantity,
    gri.uom_id,
    received_uom.uom_code as received_uom_code,
    poi.uom_id as ordered_uom_id,
    ordered_uom.uom_code as ordered_uom_code,
    gri.actual_unit_cost,
    (gri.received_quantity * gri.actual_unit_cost)::numeric(38,9) as actual_line_amount,
    gr.received_at,
    gr.supplier_invoice_number,
    gri.notes,
    gri._created_at,
    gri._last_updated_at,
    gri._is_deleted,
    gri._deleted_at
    {{ core_metadata_columns('gri', ['gr', 'poi', 'si', 'received_uom', 'ordered_uom']) }}
from source_rows gri
left join {{ ref('core_goods_receipts') }} gr
    on gri.goods_receipt_id = gr.goods_receipt_id
left join {{ ref('core_purchase_order_items') }} poi
    on gri.purchase_order_item_id = poi.purchase_order_item_id
left join {{ ref('core_stock_items') }} si
    on gri.stock_item_id = si.stock_item_id
left join {{ ref('core_units_of_measure') }} received_uom
    on gri.uom_id = received_uom.uom_id
left join {{ ref('core_units_of_measure') }} ordered_uom
    on poi.uom_id = ordered_uom.uom_id
