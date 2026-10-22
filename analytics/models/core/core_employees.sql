{{ config(description='Current-state conformed employee dimension.') }}

with source_rows as (
    {{ core_source_rows('stg_employees', 'core_employees') }}
)

select
    source_rows.employee_id,
    source_rows.branch_id,
    trim(source_rows.employee_code) as employee_code,
    source_rows.full_name,
    source_rows.role_name,
    source_rows.phone,
    source_rows.hired_on,
    source_rows.terminated_on,
    source_rows.is_active,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    source_rows._ingested_at as _record_updated_at
from source_rows

