{{ config(description='Staging copy of bakery.inventory_lots.') }}

{{ source_incremental('bakery', 'inventory_lots') }}
