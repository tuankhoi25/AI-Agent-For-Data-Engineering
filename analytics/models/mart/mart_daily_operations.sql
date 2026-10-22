{{ config(
    description='Daily production and waste operations at branch/unit grain; quantities in different units are kept separate.',
    pre_hook="{{ delete_affected_mart_rows('mart_daily_operations') }}"
) }}

with changed_keys as (
    {{ mart_changed_keys('mart_daily_operations') }}
),
production as (
    select
        pb.business_date,
        pb.branch_id,
        pb.uom_id,
        max(pb.uom_code) as uom_code,
        max(pb.branch_code) as branch_code,
        max(pb.branch_name) as branch_name,
        count(*) filter (where pb.is_completed_output) as completed_batch_count,
        (sum(pb.planned_quantity) filter (where pb.is_completed_output))::numeric(38,9) as planned_output_quantity,
        (sum(pb.produced_quantity) filter (where pb.is_completed_output))::numeric(38,9) as produced_output_quantity,
        (avg(pb.production_duration_minutes) filter (where pb.is_completed_output))::numeric(38,9) as avg_production_duration_minutes,
        max(pb._record_updated_at) as production_record_updated_at
    from {{ ref('core_production_batches') }} pb
    join changed_keys ck
        on pb.business_date is not distinct from ck.business_date
       and pb.branch_id is not distinct from ck.branch_id
       and pb.uom_id is not distinct from ck.uom_id
    where not pb._is_deleted
      and pb.business_date is not null
    group by pb.business_date, pb.branch_id, pb.uom_id
),
waste as (
    select
        w.business_date,
        w.branch_id,
        w.uom_id,
        max(w.uom_code) as uom_code,
        max(w.branch_code) as branch_code,
        max(w.branch_name) as branch_name,
        count(*) as waste_record_count,
        sum(w.quantity) as wasted_quantity,
        max(w._record_updated_at) as waste_record_updated_at
    from {{ ref('core_waste_records') }} w
    join changed_keys ck
        on w.business_date is not distinct from ck.business_date
       and w.branch_id is not distinct from ck.branch_id
       and w.uom_id is not distinct from ck.uom_id
    where not w._is_deleted
    group by w.business_date, w.branch_id, w.uom_id
)

select
    coalesce(p.business_date, w.business_date) as business_date,
    coalesce(p.branch_id, w.branch_id) as branch_id,
    coalesce(p.uom_id, w.uom_id) as uom_id,
    coalesce(p.uom_code, w.uom_code) as uom_code,
    coalesce(p.branch_code, w.branch_code) as branch_code,
    coalesce(p.branch_name, w.branch_name) as branch_name,
    coalesce(p.completed_batch_count, 0) as completed_batch_count,
    p.planned_output_quantity,
    p.produced_output_quantity,
    p.avg_production_duration_minutes,
    coalesce(w.waste_record_count, 0) as waste_record_count,
    coalesce(w.wasted_quantity, 0)::numeric(38,9) as wasted_quantity,
    greatest(
        coalesce(p.production_record_updated_at, '1900-01-01'::timestamptz),
        coalesce(w.waste_record_updated_at, '1900-01-01'::timestamptz)
    ) as _record_updated_at
from production p
full outer join waste w
    on p.business_date = w.business_date
   and p.branch_id = w.branch_id
   and p.uom_id = w.uom_id
