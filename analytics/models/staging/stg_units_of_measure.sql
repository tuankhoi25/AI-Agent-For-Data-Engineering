{{ config(description='Staging copy of bakery.units_of_measure.') }}

{{ source_incremental('bakery', 'units_of_measure') }}
