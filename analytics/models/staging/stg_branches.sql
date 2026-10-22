{{ config(description='Staging copy of bakery.branches.') }}

{{ source_incremental('bakery', 'branches') }}
