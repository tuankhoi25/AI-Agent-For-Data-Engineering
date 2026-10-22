{{ config(description='Staging copy of bakery.shifts.') }}

{{ source_incremental('bakery', 'shifts') }}
