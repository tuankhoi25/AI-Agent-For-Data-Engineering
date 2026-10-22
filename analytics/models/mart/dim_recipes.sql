{{ config(
    description='SCD2 recipe dimension with historical product and yield-unit references.',
    pre_hook="{{ ensure_scd2_sequence() }}"
) }}

with source_rows as (
    {{ scd2_dimension_rows('snap_dim_recipes', 'recipe_sk', 'recipe_id') }}
)

select
    source_rows.recipe_sk,
    source_rows.dbt_scd_id as _dimension_version_id,
    source_rows.recipe_id,
    source_rows.product_id,
    p.product_sk,
    p.sku,
    p.product_name,
    source_rows.recipe_version,
    source_rows.yield_quantity,
    source_rows.yield_uom_id,
    u.uom_sk as yield_uom_sk,
    u.uom_code as yield_uom_code,
    source_rows.effective_from,
    source_rows.effective_to,
    source_rows.instructions,
    source_rows.is_active,
    source_rows._effective_valid_from as _valid_from,
    source_rows.dbt_valid_from as _observed_from,
    source_rows.dbt_valid_to as _valid_to,
    source_rows.dbt_valid_to is null as _is_current,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    greatest(source_rows._source_last_updated_at, coalesce(source_rows.dbt_updated_at, source_rows._source_last_updated_at)) as _record_updated_at
from source_rows
left join {{ ref('dim_products') }} p
    on source_rows.product_id = p.product_id
   and source_rows._effective_valid_from >= p._valid_from
   and source_rows._effective_valid_from < coalesce(p._valid_to, '9999-12-31'::timestamptz)
left join {{ ref('dim_units_of_measure') }} u
    on source_rows.yield_uom_id = u.uom_id
   and source_rows._effective_valid_from >= u._valid_from
   and source_rows._effective_valid_from < coalesce(u._valid_to, '9999-12-31'::timestamptz)

