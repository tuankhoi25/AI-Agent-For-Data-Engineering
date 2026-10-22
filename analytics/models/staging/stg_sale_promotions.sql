{{ config(description='Staging copy of bakery.sale_promotions.') }}

{{ source_incremental('bakery', 'sale_promotions') }}
