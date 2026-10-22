{{ config(description='Cash-movement grain. Amount is positive; direction is derived from movement_type.') }}

with source_rows as (
    {{ core_source_rows('stg_cash_movements', 'core_cash_movements') }}
)

select
    cm.cash_movement_id,
    cm.shift_id,
    sh.shift_code,
    sh.branch_id,
    sh.branch_code,
    sh.business_date,
    cm.movement_type,
    cm.amount,
    (case when cm.movement_type in ('FLOAT_IN', 'SALE_CASH_IN', 'OTHER_IN') then cm.amount else 0 end)::numeric(38,9) as cash_in_amount,
    (case when cm.movement_type in ('CASH_OUT', 'REFUND_OUT', 'OTHER_OUT') then cm.amount else 0 end)::numeric(38,9) as cash_out_amount,
    (case when cm.movement_type in ('FLOAT_IN', 'SALE_CASH_IN', 'OTHER_IN') then cm.amount else -cm.amount end)::numeric(38,9) as signed_cash_amount,
    cm.occurred_at,
    cm.sale_id,
    cm.recorded_by,
    cm.description,
    cm._created_at,
    cm._last_updated_at,
    cm._is_deleted,
    cm._deleted_at
    {{ core_metadata_columns('cm', ['sh']) }}
from source_rows cm
left join {{ ref('core_shifts') }} sh
    on cm.shift_id = sh.shift_id
