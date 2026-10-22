{{ config(
    description='Daily sales KPI at branch grain. Receipt revenue preserves original invoices; refund impact is separate.',
    pre_hook="{{ delete_affected_mart_rows('mart_daily_sales') }}"
) }}

with changed_keys as (
    {{ mart_changed_keys('mart_daily_sales') }}
)

select
    f.business_date,
    f.branch_id,
    max(f.branch_code) as branch_code,
    max(f.branch_name) as branch_name,
    count(*) as order_count,
    count(*) filter (where f.customer_id is not null) as identified_customer_order_count,
    (sum(f.subtotal))::numeric(38,9) as gross_sales,
    (sum(f.discount_total))::numeric(38,9) as discount_amount,
    (sum(f.tax_total))::numeric(38,9) as tax_amount,
    (sum(f.total_amount))::numeric(38,9) as receipt_revenue,
    (sum(f.refund_amount))::numeric(38,9) as refund_amount,
    (sum(f.revenue_after_refund))::numeric(38,9) as net_revenue_after_refund,
    (sum(f.collected_payment_amount))::numeric(38,9) as collected_payment_amount,
    (sum(f.currently_captured_payment_amount))::numeric(38,9) as currently_captured_payment_amount,
    (round(sum(f.total_amount) / nullif(count(*), 0), 2))::numeric(38,9) as average_ticket,
    min(f.sale_occurred_at) as first_sale_at,
    max(f.sale_occurred_at) as last_sale_at,
    max(f._record_updated_at) as _record_updated_at
from {{ ref('fct_sales') }} f
join changed_keys ck
    on f.business_date is not distinct from ck.business_date
   and f.branch_id is not distinct from ck.branch_id
where not f._is_deleted
  and f.is_sale_completed
group by f.business_date, f.branch_id
