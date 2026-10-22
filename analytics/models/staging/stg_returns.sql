{{ config(description='Staging copy of bakery.returns.') }}

{{ source_incremental('bakery', 'returns') }}
