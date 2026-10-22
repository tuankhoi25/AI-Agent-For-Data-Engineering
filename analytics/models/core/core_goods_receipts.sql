{{ config(description='Goods-receipt header grain; a receipt may be independent of a purchase order.') }}

with source_rows as (
    {{ core_source_rows('stg_goods_receipts', 'core_goods_receipts') }}
)

select
    gr.goods_receipt_id,
    trim(gr.receipt_number) as receipt_number,
    gr.purchase_order_id,
    po.po_number,
    gr.supplier_id,
    s.supplier_code,
    s.supplier_name,
    gr.branch_id,
    b.branch_code,
    b.branch_name,
    gr.received_at,
    gr.received_by,
    e.employee_code as received_by_employee_code,
    gr.supplier_invoice_number,
    gr.notes,
    gr._created_at,
    gr._last_updated_at,
    gr._is_deleted,
    gr._deleted_at
    {{ core_metadata_columns('gr', ['po', 's', 'b', 'e']) }}
from source_rows gr
left join {{ ref('core_purchase_orders') }} po
    on gr.purchase_order_id = po.purchase_order_id
left join {{ ref('core_suppliers') }} s
    on gr.supplier_id = s.supplier_id
left join {{ ref('core_branches') }} b
    on gr.branch_id = b.branch_id
left join {{ ref('core_employees') }} e
    on gr.received_by = e.employee_id
