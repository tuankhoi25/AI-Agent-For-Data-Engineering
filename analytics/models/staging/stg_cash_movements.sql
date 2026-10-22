{{ config(description='Staging copy of bakery.cash_movements.') }}

{{ source_incremental('bakery', 'cash_movements') }}
