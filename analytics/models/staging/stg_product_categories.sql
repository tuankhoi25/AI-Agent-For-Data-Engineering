{{ config(description='Staging copy of bakery.product_categories.') }}

{{ source_incremental('bakery', 'product_categories') }}
