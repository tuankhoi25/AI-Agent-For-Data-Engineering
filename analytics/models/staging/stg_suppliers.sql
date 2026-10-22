{{ config(description='Staging copy of bakery.suppliers.') }}

{{ source_incremental('bakery', 'suppliers') }}
