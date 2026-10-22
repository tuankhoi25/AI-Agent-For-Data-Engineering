{{ config(
    description='Customer-level sales and loyalty summary. Customers without purchases remain visible.',
    pre_hook="{{ delete_affected_mart_rows('mart_customer_360') }}"
) }}

with changed_keys as (
    {{ mart_changed_keys('mart_customer_360') }}
),
sales as (
    select
        f.customer_id,
        count(*) as order_count,
        sum(f.total_amount) as receipt_revenue,
        sum(f.refund_amount) as refund_amount,
        sum(f.revenue_after_refund) as net_revenue_after_refund,
        min(f.sale_occurred_at) as first_sale_at,
        max(f.sale_occurred_at) as last_sale_at,
        max(f._record_updated_at) as sales_record_updated_at
    from {{ ref('fct_sales') }} f
    join changed_keys ck
        on f.customer_id is not distinct from ck.customer_id
    where not f._is_deleted
      and f.is_sale_completed
      and f.customer_id is not null
    group by f.customer_id
),
loyalty_ranked as (
    select
        lt.customer_id,
        lt.points_balance_after_transaction,
        lt._record_updated_at,
        row_number() over (
            partition by lt.customer_id
            order by lt.occurred_at desc, lt.loyalty_transaction_id desc
        ) as row_num
    from {{ ref('core_loyalty_transactions') }} lt
    join changed_keys ck
        on lt.customer_id is not distinct from ck.customer_id
    where not lt._is_deleted
),
loyalty as (
    select
        customer_id,
        points_balance_after_transaction,
        _record_updated_at as loyalty_record_updated_at
    from loyalty_ranked
    where row_num = 1
)

select
    c.customer_id,
    c.customer_code,
    c.full_name,
    c.phone,
    c.email,
    c.joined_at,
    c.marketing_consent,
    c.is_active,
    coalesce(s.order_count, 0) as order_count,
    coalesce(s.receipt_revenue, 0)::numeric(38,9) as receipt_revenue,
    coalesce(s.refund_amount, 0)::numeric(38,9) as refund_amount,
    coalesce(s.net_revenue_after_refund, 0)::numeric(38,9) as net_revenue_after_refund,
    s.first_sale_at,
    s.last_sale_at,
    coalesce(l.points_balance_after_transaction, 0) as current_points_balance,
    s.customer_id is not null as has_purchased,
    greatest(
        c._record_updated_at,
        coalesce(s.sales_record_updated_at, c._record_updated_at),
        coalesce(l.loyalty_record_updated_at, c._record_updated_at)
    ) as _record_updated_at
from {{ ref('dim_customers') }} c
join changed_keys ck
    on c.customer_id is not distinct from ck.customer_id
   and c._is_current
left join sales s
    on c.customer_id is not distinct from s.customer_id
left join loyalty l
    on c.customer_id is not distinct from l.customer_id
where not c._is_deleted
