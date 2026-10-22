{{ config(description='Staging copy of bakery.sales.') }}

{{ source_incremental('bakery', 'sales') }}
