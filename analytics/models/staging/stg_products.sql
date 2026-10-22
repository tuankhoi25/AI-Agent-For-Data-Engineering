{{ config(description='Staging copy of bakery.products.') }}

{{ source_incremental('bakery', 'products') }}
