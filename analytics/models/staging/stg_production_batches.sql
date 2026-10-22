{{ config(description='Staging copy of bakery.production_batches.') }}

{{ source_incremental('bakery', 'production_batches') }}
