{{ config(description='Staging copy of bakery.return_items.') }}

{{ source_incremental('bakery', 'return_items') }}
