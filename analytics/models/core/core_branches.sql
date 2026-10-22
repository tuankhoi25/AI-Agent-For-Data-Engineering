{{ config(description='Current-state conformed branch dimension. Business dates use Asia/Ho_Chi_Minh.') }}

with source_rows as (
    {{ core_source_rows('stg_branches', 'core_branches') }}
)

select
    source_rows.branch_id,
    trim(source_rows.branch_code) as branch_code,
    source_rows.branch_name,
    source_rows.address,
    source_rows.phone,
    source_rows.timezone,
    source_rows.opening_date,
    source_rows.is_active,
    source_rows.notes,
    source_rows.created_at,
    source_rows._created_at,
    source_rows._last_updated_at,
    source_rows._is_deleted,
    source_rows._deleted_at,
    source_rows._source_last_updated_at,
    source_rows._ingested_at as _source_ingested_at,
    source_rows._ingested_at as _record_updated_at
from source_rows

