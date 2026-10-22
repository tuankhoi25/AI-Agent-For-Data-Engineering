{{ config(description='Staging copy of bakery.recipes.') }}

{{ source_incremental('bakery', 'recipes') }}
