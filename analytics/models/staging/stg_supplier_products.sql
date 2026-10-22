{{ config(description='Staging copy of bakery.supplier_products.') }}

{{ source_incremental('bakery', 'supplier_products') }}
