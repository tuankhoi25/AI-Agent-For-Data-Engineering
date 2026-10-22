{{ config(description='Staging copy of bakery.customers.') }}

{{ source_incremental('bakery', 'customers') }}
