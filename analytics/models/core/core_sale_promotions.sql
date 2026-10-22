{{ config(description='Applied-promotion grain with actual discount amounts.') }}

with source_rows as (
    {{ core_source_rows('stg_sale_promotions', 'core_sale_promotions') }}
)

select
    sp.sale_promotion_id,
    sp.sale_id,
    s.receipt_number,
    s.branch_id,
    s.business_date,
    sp.promotion_id,
    p.promotion_code,
    p.promotion_name,
    p.promotion_type,
    sp.discount_amount,
    sp.coupon_code,
    sp.applied_at,
    sp._created_at,
    sp._last_updated_at,
    sp._is_deleted,
    sp._deleted_at
    {{ core_metadata_columns('sp', ['s', 'p']) }}
from source_rows sp
left join {{ ref('core_sales') }} s
    on sp.sale_id = s.sale_id
left join {{ ref('core_promotions') }} p
    on sp.promotion_id = p.promotion_id
