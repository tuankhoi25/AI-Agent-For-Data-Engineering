{{ config(description='Recipe component grain; quantities are kept in the declared component unit.') }}

with source_rows as (
    {{ core_source_rows('stg_recipe_items', 'core_recipe_items') }}
)

select
    ri.recipe_item_id,
    ri.recipe_id,
    r.product_id,
    r.sku,
    r.product_name,
    ri.stock_item_id,
    si.stock_item_code,
    si.stock_item_name,
    ri.quantity,
    ri.uom_id,
    u.uom_code,
    ri.is_optional,
    ri.notes,
    ri._created_at,
    ri._last_updated_at,
    ri._is_deleted,
    ri._deleted_at
    {{ core_metadata_columns('ri', ['r', 'si', 'u']) }}
from source_rows ri
left join {{ ref('core_recipes') }} r
    on ri.recipe_id = r.recipe_id
left join {{ ref('core_stock_items') }} si
    on ri.stock_item_id = si.stock_item_id
left join {{ ref('core_units_of_measure') }} u
    on ri.uom_id = u.uom_id
