{{ config(
    description='Shift cash reconciliation. Non-cash payments are not included in cash drawer movement.',
    pre_hook="{{ delete_affected_mart_rows('mart_cash_reconciliation') }}"
) }}

with changed_keys as (
    {{ mart_changed_keys('mart_cash_reconciliation') }}
),
movements as (
    select
        cm.shift_id,
        sum(cm.cash_in_amount) as cash_in_amount,
        sum(cm.cash_out_amount) as cash_out_amount,
        sum(cm.signed_cash_amount) as net_cash_movement,
        count(*) as cash_movement_count,
        max(cm._record_updated_at) as movement_record_updated_at
    from {{ ref('core_cash_movements') }} cm
    join changed_keys ck
        on cm.shift_id is not distinct from ck.shift_id
    where not cm._is_deleted
    group by cm.shift_id
)

select
    sh.shift_id,
    sh.shift_code,
    sh.branch_id,
    sh.branch_code,
    sh.branch_name,
    sh.business_date,
    sh.employee_id,
    sh.employee_code,
    sh.employee_name,
    sh.opened_at,
    sh.closed_at,
    sh.status,
    sh.opening_cash,
    coalesce(m.cash_in_amount, 0)::numeric(38,9) as cash_in_amount,
    coalesce(m.cash_out_amount, 0)::numeric(38,9) as cash_out_amount,
    (sh.opening_cash + coalesce(m.net_cash_movement, 0))::numeric(38,9) as expected_ending_cash,
    sh.counted_cash,
    (case
        when sh.counted_cash is null then null::numeric(38,9)
        else sh.counted_cash - (sh.opening_cash + coalesce(m.net_cash_movement, 0))
    end)::numeric(38,9) as cash_variance,
    coalesce(m.cash_movement_count, 0) as cash_movement_count,
    greatest(
        sh._record_updated_at,
        coalesce(m.movement_record_updated_at, sh._record_updated_at)
    ) as _record_updated_at
from {{ ref('core_shifts') }} sh
join changed_keys ck
    on sh.shift_id is not distinct from ck.shift_id
left join movements m
    on sh.shift_id is not distinct from m.shift_id
where not sh._is_deleted
