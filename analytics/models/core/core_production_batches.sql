{{ config(description='Production-batch grain; planned quantity is not treated as actual output.') }}

with source_rows as (
    {{ core_source_rows('stg_production_batches', 'core_production_batches') }}
)

select
    pb.production_batch_id,
    trim(pb.batch_number) as batch_number,
    pb.branch_id,
    b.branch_code,
    b.branch_name,
    pb.product_id,
    p.sku,
    p.product_name,
    p.product_type,
    pb.recipe_id,
    r.recipe_version,
    pb.planned_quantity,
    pb.produced_quantity,
    pb.uom_id,
    u.uom_code,
    pb.status,
    pb.started_at,
    pb.completed_at,
    (coalesce(pb.completed_at, pb.started_at) at time zone 'Asia/Ho_Chi_Minh')::date as business_date,
    (extract(epoch from (pb.completed_at - pb.started_at)) / 60.0)::numeric(38,9) as production_duration_minutes,
    pb.produced_by,
    e.employee_code as produced_by_employee_code,
    pb.notes,
    pb.status = 'COMPLETED' and pb.completed_at is not null as is_completed_output,
    pb._created_at,
    pb._last_updated_at,
    pb._is_deleted,
    pb._deleted_at
    {{ core_metadata_columns('pb', ['b', 'p', 'r', 'u', 'e']) }}
from source_rows pb
left join {{ ref('core_branches') }} b
    on pb.branch_id = b.branch_id
left join {{ ref('core_products') }} p
    on pb.product_id = p.product_id
left join {{ ref('core_recipes') }} r
    on pb.recipe_id = r.recipe_id
left join {{ ref('core_units_of_measure') }} u
    on pb.uom_id = u.uom_id
left join {{ ref('core_employees') }} e
    on pb.produced_by = e.employee_id
