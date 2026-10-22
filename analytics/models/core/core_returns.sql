{{ config(description='Return-document grain. Only COMPLETED returns affect refund and restock reporting.') }}

with source_rows as (
    {{ core_source_rows('stg_returns', 'core_returns') }}
)

select
    r.return_id,
    trim(r.return_number) as return_number,
    r.sale_id,
    s.receipt_number,
    s.branch_id,
    s.business_date as sale_business_date,
    r.processed_by,
    r.returned_at,
    (r.returned_at at time zone 'Asia/Ho_Chi_Minh')::date as return_business_date,
    r.reason,
    r.status,
    r.refund_total,
    r.status = 'COMPLETED' as is_completed_return,
    r._created_at,
    r._last_updated_at,
    r._is_deleted,
    r._deleted_at
    {{ core_metadata_columns('r', ['s']) }}
from source_rows r
left join {{ ref('core_sales') }} s
    on r.sale_id = s.sale_id
