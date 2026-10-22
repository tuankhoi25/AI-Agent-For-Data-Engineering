{{ config(description='Staging copy of bakery.sale_items.') }}

{{ source_incremental('bakery', 'sale_items') }}
