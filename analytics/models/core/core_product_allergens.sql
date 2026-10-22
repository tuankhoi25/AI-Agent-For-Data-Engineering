{{ config(description='Product/allergen bridge with product and allergen labels.') }}

with source_rows as (
    {{ core_source_rows('stg_product_allergens', 'core_product_allergens') }}
)

select
    pa.product_id,
    p.sku,
    p.product_name,
    pa.allergen_id,
    a.allergen_code,
    a.allergen_name,
    pa.is_confirmed,
    pa.notes,
    pa._created_at,
    pa._last_updated_at,
    pa._is_deleted,
    pa._deleted_at
    {{ core_metadata_columns('pa', ['p', 'a']) }}
from source_rows pa
left join {{ ref('core_products') }} p
    on pa.product_id = p.product_id
left join {{ ref('core_allergens') }} a
    on pa.allergen_id = a.allergen_id
