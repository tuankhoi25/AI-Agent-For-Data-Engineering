{{ config(description='Staging copy of bakery.employees.') }}

{{ source_incremental('bakery', 'employees') }}
