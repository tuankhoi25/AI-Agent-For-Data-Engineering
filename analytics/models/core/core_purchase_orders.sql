{{ config(description='Purchase-order header grain; order creation does not increase inventory.') }}

with source_rows as (
    {{ core_source_rows('stg_purchase_orders', 'core_purchase_orders') }}
)

select
    po.purchase_order_id,
    trim(po.po_number) as po_number,
    po.supplier_id,
    s.supplier_code,
    s.supplier_name,
    po.branch_id,
    b.branch_code,
    b.branch_name,
    po.ordered_at,
    po.expected_at,
    po.status,
    trim(po.currency_code) as currency_code,
    po.notes,
    po.created_by,
    e.employee_code as created_by_employee_code,
    po._created_at,
    po._last_updated_at,
    po._is_deleted,
    po._deleted_at
    {{ core_metadata_columns('po', ['s', 'b', 'e']) }}
from source_rows po
left join {{ ref('core_suppliers') }} s
    on po.supplier_id = s.supplier_id
left join {{ ref('core_branches') }} b
    on po.branch_id = b.branch_id
left join {{ ref('core_employees') }} e
    on po.created_by = e.employee_id
