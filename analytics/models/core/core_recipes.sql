{{ config(description='Current-state conformed recipe dimension; business effective dates remain source attributes.') }}

with source_rows as (
    {{ core_source_rows('stg_recipes', 'core_recipes') }}
)

select
    source_rows.recipe_id,
    source_rows.product_id,
    p.sku,
    p.product_name,
    source_rows.recipe_version,
    source_rows.yield_quantity,
    source_rows.yield_uom_id,
    u.uom_code as yield_uom_code,
    source_rows.effective_from,
    source_rows.effective_to,
    source_rows.instructions,
    source_rows.is_active,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    greatest(
        source_rows._ingested_at,
        coalesce(p._record_updated_at, source_rows._ingested_at),
        coalesce(u._record_updated_at, source_rows._ingested_at)
    ) as _record_updated_at
from source_rows
left join {{ ref('core_products') }} p
    on source_rows.product_id = p.product_id
left join {{ ref('core_units_of_measure') }} u
    on source_rows.yield_uom_id = u.uom_id

