{{ config(description='Promotion/product eligibility bridge.') }}

with source_rows as (
    {{ core_source_rows('stg_promotion_products', 'core_promotion_products') }}
)

select
    pp.promotion_id,
    p.promotion_code,
    p.promotion_name,
    pp.product_id,
    pr.sku,
    pr.product_name,
    pr.category_code,
    p.promotion_type,
    pp._created_at,
    pp._last_updated_at,
    pp._is_deleted,
    pp._deleted_at
    {{ core_metadata_columns('pp', ['p', 'pr']) }}
from source_rows pp
left join {{ ref('core_promotions') }} p
    on pp.promotion_id = p.promotion_id
left join {{ ref('core_products') }} pr
    on pp.product_id = pr.product_id
