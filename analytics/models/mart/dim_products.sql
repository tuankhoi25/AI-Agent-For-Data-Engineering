{{ config(
    description='SCD2 sellable-product dimension with a durable surrogate key and historical parent dimension keys.',
    pre_hook="{{ ensure_scd2_sequence() }}"
) }}

with source_rows as (
    {{ scd2_dimension_rows('snap_dim_products', 'product_sk', 'product_id') }}
)

select
    source_rows.product_sk,
    source_rows.dbt_scd_id as _dimension_version_id,
    source_rows.product_id,
    trim(source_rows.sku) as sku,
    source_rows.product_name,
    source_rows.category_id,
    c.category_sk,
    c.category_code,
    c.category_name,
    source_rows.product_type,
    source_rows.sell_uom_id,
    sell_uom.uom_sk as sell_uom_sk,
    sell_uom.uom_code as sell_uom_code,
    source_rows.stock_item_id,
    si.stock_item_sk,
    si.stock_item_code,
    si.item_type as stock_item_type,
    source_rows.description,
    source_rows.ingredient_summary,
    source_rows.unit_price,
    source_rows.is_active,
    source_rows.available_from,
    source_rows.available_to,
    source_rows.created_at,
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
left join {{ ref('dim_product_categories') }} c
    on source_rows.category_id = c.category_id
   and source_rows._effective_valid_from >= c._valid_from
   and source_rows._effective_valid_from < coalesce(c._valid_to, '9999-12-31'::timestamptz)
left join {{ ref('dim_units_of_measure') }} sell_uom
    on source_rows.sell_uom_id = sell_uom.uom_id
   and source_rows._effective_valid_from >= sell_uom._valid_from
   and source_rows._effective_valid_from < coalesce(sell_uom._valid_to, '9999-12-31'::timestamptz)
left join {{ ref('dim_stock_items') }} si
    on source_rows.stock_item_id = si.stock_item_id
   and source_rows._effective_valid_from >= si._valid_from
   and source_rows._effective_valid_from < coalesce(si._valid_to, '9999-12-31'::timestamptz)

