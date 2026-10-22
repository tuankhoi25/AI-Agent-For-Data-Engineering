{{ config(description='Staging copy of bakery.promotions.') }}

{{ source_incremental('bakery', 'promotions') }}
