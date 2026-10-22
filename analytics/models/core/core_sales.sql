{{ config(description='Sales-receipt grain. Completed and refunded states remain sales history; refunds are modeled separately.') }}

with source_rows as (
    {{ core_source_rows('stg_sales', 'core_sales') }}
)

select
    s.sale_id,
    trim(s.receipt_number) as receipt_number,
    s.branch_id,
    b.branch_code,
    b.branch_name,
    s.customer_id,
    c.customer_code,
    s.cashier_id,
    e.employee_code as cashier_employee_code,
    s.channel,
    s.status,
    s.opened_at,
    s.completed_at,
    coalesce(s.completed_at, s.opened_at) as sale_occurred_at,
    (coalesce(s.completed_at, s.opened_at) at time zone 'Asia/Ho_Chi_Minh')::date as business_date,
    s.subtotal,
    s.discount_total,
    s.tax_total,
    s.total_amount,
    'VND'::char(3) as currency_code,
    s.idempotency_key,
    s.notes,
    s.status in ('COMPLETED', 'PARTIALLY_REFUNDED', 'REFUNDED') as is_sale_completed,
    s._created_at,
    s._last_updated_at,
    s._is_deleted,
    s._deleted_at
    {{ core_metadata_columns('s', ['b', 'c', 'e']) }}
from source_rows s
left join {{ ref('core_branches') }} b
    on s.branch_id = b.branch_id
left join {{ ref('core_customers') }} c
    on s.customer_id = c.customer_id
left join {{ ref('core_employees') }} e
    on s.cashier_id = e.employee_id
