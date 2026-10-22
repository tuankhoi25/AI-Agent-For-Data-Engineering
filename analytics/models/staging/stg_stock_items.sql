{{ config(description='Staging copy of bakery.stock_items.') }}

{{ source_incremental('bakery', 'stock_items') }}
