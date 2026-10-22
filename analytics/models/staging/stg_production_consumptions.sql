{{ config(description='Staging copy of bakery.production_consumptions.') }}

{{ source_incremental('bakery', 'production_consumptions') }}
