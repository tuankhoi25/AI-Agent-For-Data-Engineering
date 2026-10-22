{{ config(description='Loyalty transaction grain with point balance ordered by event time.') }}

with source_rows as (
    {{ core_partition_source_rows('stg_loyalty_transactions', 'core_loyalty_transactions') }}
)

select
    lt.loyalty_transaction_id,
    lt.customer_id,
    c.customer_code,
    lt.sale_id,
    s.receipt_number,
    lt.transaction_type,
    lt.points_delta,
    lt.occurred_at,
    (lt.occurred_at at time zone 'Asia/Ho_Chi_Minh')::date as business_date,
    sum(case when not lt._is_deleted then lt.points_delta else 0 end) over (
        partition by lt.customer_id
        order by lt.occurred_at, lt.loyalty_transaction_id
        rows between unbounded preceding and current row
    ) as points_balance_after_transaction,
    lt.idempotency_key,
    lt.notes,
    lt._created_at,
    lt._last_updated_at,
    lt._is_deleted,
    lt._deleted_at
    , lt._source_last_updated_at
    , lt._ingested_at as _source_ingested_at
    , greatest(
        lt._ingested_at,
        coalesce(lt._partition_recomputed_at, lt._ingested_at),
        coalesce(c._record_updated_at, lt._ingested_at),
        coalesce(s._record_updated_at, lt._ingested_at)
      ) as _record_updated_at
from source_rows lt
left join {{ ref('core_customers') }} c
    on lt.customer_id = c.customer_id
left join {{ ref('core_sales') }} s
    on lt.sale_id = s.sale_id
