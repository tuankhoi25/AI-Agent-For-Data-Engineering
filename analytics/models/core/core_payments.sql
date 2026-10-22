{{ config(description='Payment-attempt grain. Failed attempts are excluded from collected-payment metrics.') }}

with source_rows as (
    {{ core_source_rows('stg_payments', 'core_payments') }}
)

select
    p.payment_id,
    p.sale_id,
    s.receipt_number,
    s.branch_id,
    s.business_date,
    p.payment_method,
    p.amount,
    trim(p.currency_code) as currency_code,
    p.status,
    p.paid_at,
    p.provider_reference,
    p.notes,
    p.status in ('CAPTURED', 'REFUNDED') as is_successful_payment,
    p.status = 'CAPTURED' as is_currently_captured,
    p._created_at,
    p._last_updated_at,
    p._is_deleted,
    p._deleted_at
    {{ core_metadata_columns('p', ['s']) }}
from source_rows p
left join {{ ref('core_sales') }} s
    on p.sale_id = s.sale_id
