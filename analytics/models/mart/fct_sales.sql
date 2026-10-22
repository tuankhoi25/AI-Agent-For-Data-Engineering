{{ config(description='Sales-receipt fact at one row per sale, with payments and completed returns aggregated separately.') }}

with changed_keys as (
    {% if is_incremental() %}
        {{ changed_keys_with_watermark('sale_id', ['core_sales', 'core_payments', 'core_return_items']) }}
    {% else %}
        select sale_id, null::timestamptz as changed_record_updated_at
        from {{ ref('core_sales') }}
    {% endif %}
),
payment_totals as (
    select
        p.sale_id,
        sum(p.amount) filter (where p.is_successful_payment) as collected_payment_amount,
        sum(p.amount) filter (where p.is_currently_captured) as currently_captured_payment_amount,
        count(*) filter (where p.is_successful_payment) as successful_payment_count,
        max(p._record_updated_at) as payment_record_updated_at
    from {{ ref('core_payments') }} p
    join changed_keys ck
        on p.sale_id = ck.sale_id
    where not p._is_deleted
    group by p.sale_id
),
return_totals as (
    select
        r.sale_id,
        sum(r.refund_amount) filter (where r.is_completed_return) as refund_amount,
        sum(r.quantity) filter (where r.is_completed_return) as returned_quantity,
        sum(r.quantity) filter (where r.is_completed_return and r.restockable) as restocked_quantity,
        max(r._record_updated_at) as return_record_updated_at
    from {{ ref('core_return_items') }} r
    join changed_keys ck
        on r.sale_id = ck.sale_id
    where not r._is_deleted
    group by r.sale_id
)

select
    s.sale_id,
    s.receipt_number,
    s.branch_id,
    b_dim.branch_sk,
    coalesce(b_dim.branch_code, s.branch_code) as branch_code,
    coalesce(b_dim.branch_name, s.branch_name) as branch_name,
    s.customer_id,
    c_dim.customer_sk,
    coalesce(c_dim.customer_code, s.customer_code) as customer_code,
    s.cashier_id,
    e_dim.employee_sk,
    coalesce(e_dim.employee_code, s.cashier_employee_code) as cashier_employee_code,
    s.channel,
    s.status,
    s.opened_at,
    s.completed_at,
    s.sale_occurred_at,
    s.business_date,
    s.subtotal,
    s.discount_total,
    s.tax_total,
    s.total_amount,
    s.currency_code,
    coalesce(pt.collected_payment_amount, 0)::numeric(38,9) as collected_payment_amount,
    coalesce(pt.currently_captured_payment_amount, 0)::numeric(38,9) as currently_captured_payment_amount,
    coalesce(pt.successful_payment_count, 0) as successful_payment_count,
    coalesce(rt.refund_amount, 0)::numeric(38,9) as refund_amount,
    coalesce(rt.returned_quantity, 0)::numeric(38,9) as returned_quantity,
    coalesce(rt.restocked_quantity, 0)::numeric(38,9) as restocked_quantity,
    ((s.total_amount - coalesce(rt.refund_amount, 0)))::numeric(38,9) as revenue_after_refund,
    s.is_sale_completed,
    s._created_at,
    s._last_updated_at,
    s._is_deleted,
    s._deleted_at,
    greatest(
        s._record_updated_at,
        coalesce(pt.payment_record_updated_at, s._record_updated_at),
        coalesce(rt.return_record_updated_at, s._record_updated_at),
        coalesce(ck.changed_record_updated_at, s._record_updated_at)
    ) as _record_updated_at
from {{ ref('core_sales') }} s
join changed_keys ck
    on s.sale_id = ck.sale_id
left join payment_totals pt
    on s.sale_id = pt.sale_id
left join return_totals rt
    on s.sale_id = rt.sale_id
left join {{ ref('dim_branches') }} b_dim
    on s.branch_id = b_dim.branch_id
   and s.sale_occurred_at >= b_dim._valid_from
   and s.sale_occurred_at < coalesce(b_dim._valid_to, '9999-12-31'::timestamptz)
left join {{ ref('dim_customers') }} c_dim
    on s.customer_id = c_dim.customer_id
   and s.sale_occurred_at >= c_dim._valid_from
   and s.sale_occurred_at < coalesce(c_dim._valid_to, '9999-12-31'::timestamptz)
left join {{ ref('dim_employees') }} e_dim
    on s.cashier_id = e_dim.employee_id
   and s.sale_occurred_at >= e_dim._valid_from
   and s.sale_occurred_at < coalesce(e_dim._valid_to, '9999-12-31'::timestamptz)

