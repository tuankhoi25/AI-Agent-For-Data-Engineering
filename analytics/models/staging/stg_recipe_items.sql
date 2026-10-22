{{ config(description='Staging copy of bakery.recipe_items.') }}

{{ source_incremental('bakery', 'recipe_items') }}
