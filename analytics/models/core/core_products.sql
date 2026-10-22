{{ config(description='Current-state conformed sellable-product dimension enriched with menu category and stock item.') }}

with source_rows as (
    {{ core_source_rows('stg_products', 'core_products') }}
)

select
    source_rows.product_id,
    trim(source_rows.sku) as sku,
    source_rows.product_name,
    source_rows.category_id,
    c.category_code,
    c.category_name,
    source_rows.product_type,
    source_rows.sell_uom_id,
    sell_uom.uom_code as sell_uom_code,
    source_rows.stock_item_id,
    si.stock_item_code,
    si.item_type as stock_item_type,
    source_rows.description,
    source_rows.ingredient_summary,
    source_rows.unit_price,
    source_rows.is_active,
    source_rows.available_from,
    source_rows.available_to,
    source_rows.created_at,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    greatest(
        source_rows._ingested_at,
        coalesce(c._record_updated_at, source_rows._ingested_at),
        coalesce(sell_uom._record_updated_at, source_rows._ingested_at),
        coalesce(si._record_updated_at, source_rows._ingested_at)
    ) as _record_updated_at
from source_rows
left join {{ ref('core_product_categories') }} c
    on source_rows.category_id = c.category_id
left join {{ ref('core_units_of_measure') }} sell_uom
    on source_rows.sell_uom_id = sell_uom.uom_id
left join {{ ref('core_stock_items') }} si
    on source_rows.stock_item_id = si.stock_item_id

