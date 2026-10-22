{{ config(description='Supplier-stock-item bridge with reference cost and purchasing units.') }}

with source_rows as (
    {{ core_source_rows('stg_supplier_products', 'core_supplier_products') }}
)

select
    sp.supplier_product_id,
    sp.supplier_id,
    s.supplier_code,
    s.supplier_name,
    sp.stock_item_id,
    si.stock_item_code,
    si.stock_item_name,
    sp.supplier_sku,
    sp.brand_name,
    sp.purchase_uom_id,
    purchase_uom.uom_code as purchase_uom_code,
    sp.pack_size,
    sp.pack_uom_id,
    pack_uom.uom_code as pack_uom_code,
    sp.last_known_unit_cost,
    trim(sp.currency_code) as currency_code,
    sp.is_active,
    sp.notes,
    sp._created_at,
    sp._last_updated_at,
    sp._is_deleted,
    sp._deleted_at
    {{ core_metadata_columns('sp', ['s', 'si', 'purchase_uom', 'pack_uom']) }}
from source_rows sp
left join {{ ref('core_suppliers') }} s
    on sp.supplier_id = s.supplier_id
left join {{ ref('core_stock_items') }} si
    on sp.stock_item_id = si.stock_item_id
left join {{ ref('core_units_of_measure') }} purchase_uom
    on sp.purchase_uom_id = purchase_uom.uom_id
left join {{ ref('core_units_of_measure') }} pack_uom
    on sp.pack_uom_id = pack_uom.uom_id
