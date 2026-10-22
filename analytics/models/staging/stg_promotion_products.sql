{{ config(description='Staging copy of bakery.promotion_products.') }}

{{ source_incremental('bakery', 'promotion_products') }}
