{{ config(description='Staging copy of bakery.waste_records.') }}

{{ source_incremental('bakery', 'waste_records') }}
