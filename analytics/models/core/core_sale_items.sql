{{ config(description='Sales-line grain. Snapshot name, unit and price are authoritative for historical sales.') }}

with source_rows as (
    {{ core_source_rows('stg_sale_items', 'core_sale_items') }}
)

select
    si.sale_item_id,
    si.sale_id,
    s.receipt_number,
    s.branch_id,
    s.branch_code,
    s.branch_name,
    s.customer_id,
    s.business_date,
    s.sale_occurred_at,
    s.channel,
    s.status as sale_status,
    si.product_id,
    p.sku,
    p.product_name,
    p.category_code,
    p.category_name,
    p.product_type,
    si.quantity,
    si.uom_id,
    u.uom_code,
    si.product_name_snapshot,
    si.unit_price,
    (si.quantity * si.unit_price)::numeric(38,9) as gross_line_amount,
    si.discount_amount,
    si.line_total,
    si.line_total as line_amount_after_recorded_discount,
    si.notes,
    s.is_sale_completed,
    si._created_at,
    si._last_updated_at,
    si._is_deleted,
    si._deleted_at
    {{ core_metadata_columns('si', ['s', 'p', 'u']) }}
from source_rows si
left join {{ ref('core_sales') }} s
    on si.sale_id = s.sale_id
left join {{ ref('core_products') }} p
    on si.product_id = p.product_id
left join {{ ref('core_units_of_measure') }} u
    on si.uom_id = u.uom_id
