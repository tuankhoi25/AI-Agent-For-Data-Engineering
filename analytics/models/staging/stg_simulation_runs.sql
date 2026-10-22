{{ config(
    description='Staging copy of bakery.simulation_runs. This generator-control table is intentionally outside the row-audit contract.',
    materialized='table'
) }}

select *
from {{ source('bakery', 'simulation_runs') }}
