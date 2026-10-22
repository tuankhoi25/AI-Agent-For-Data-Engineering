{{ config(description='Shift grain with local business date.') }}

with source_rows as (
    {{ core_source_rows('stg_shifts', 'core_shifts') }}
)

select
    sh.shift_id,
    sh.branch_id,
    b.branch_code,
    b.branch_name,
    sh.employee_id,
    e.employee_code,
    e.full_name as employee_name,
    trim(sh.shift_code) as shift_code,
    sh.opened_at,
    sh.closed_at,
    (sh.opened_at at time zone 'Asia/Ho_Chi_Minh')::date as business_date,
    sh.opening_cash,
    sh.counted_cash,
    sh.status,
    sh.notes,
    sh._created_at,
    sh._last_updated_at,
    sh._is_deleted,
    sh._deleted_at
    {{ core_metadata_columns('sh', ['b', 'e']) }}
from source_rows sh
left join {{ ref('core_branches') }} b
    on sh.branch_id = b.branch_id
left join {{ ref('core_employees') }} e
    on sh.employee_id = e.employee_id
