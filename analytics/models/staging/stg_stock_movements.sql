{{ config(description='Staging copy of bakery.stock_movements.') }}

{{ source_incremental('bakery', 'stock_movements') }}
