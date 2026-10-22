{{ config(description='Staging copy of bakery.allergens.') }}

{{ source_incremental('bakery', 'allergens') }}
