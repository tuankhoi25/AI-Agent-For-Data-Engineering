{{ config(description='Staging copy of bakery.product_allergens.') }}

{{ source_incremental('bakery', 'product_allergens') }}
