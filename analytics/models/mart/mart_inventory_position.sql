{{ config(
    description='Current inventory position at branch/item/lot grain from signed stock movements. Positive availability excludes expired lots.',
    pre_hook="{{ delete_affected_mart_rows('mart_inventory_position') }}",
    post_hook="{{ refresh_inventory_position_as_of_run() }}"
) }}

with changed_keys as (
    {{ mart_changed_keys('mart_inventory_position') }}
),
balances as (
    select
        sm.branch_id,
        sm.stock_item_id,
        sm.inventory_lot_id,
        sum(sm.quantity_delta) as on_hand_quantity,
        max(sm.uom_code) as movement_uom_code,
        max(sm._record_updated_at) as movement_record_updated_at
    from {{ ref('core_stock_movements') }} sm
    join changed_keys ck
        on sm.branch_id is not distinct from ck.branch_id
       and sm.stock_item_id is not distinct from ck.stock_item_id
       and sm.inventory_lot_id is not distinct from ck.inventory_lot_id
    where not sm._is_deleted
    group by sm.branch_id, sm.stock_item_id, sm.inventory_lot_id
)

select
    current_date as as_of_date,
    bal.branch_id,
    b.branch_code,
    b.branch_name,
    bal.stock_item_id,
    si.stock_item_code,
    si.stock_item_name,
    si.item_type,
    si.base_uom_code,
    bal.inventory_lot_id,
    l.lot_code,
    l.manufactured_at,
    l.received_at,
    l.expires_at,
    l.unit_cost,
    bal.movement_uom_code,
    bal.on_hand_quantity::numeric(38,9) as on_hand_quantity,
    greatest(bal.on_hand_quantity, 0)::numeric(38,9) as positive_on_hand_quantity,
    (case
        when l.expires_at is not null and l.expires_at < current_date then 0::numeric(38,9)
        else greatest(bal.on_hand_quantity, 0)::numeric(38,9)
    end)::numeric(38,9) as available_quantity,
    l.expires_at is not null and l.expires_at < current_date as is_expired_as_of_run,
    bal.movement_record_updated_at as _record_updated_at
from balances bal
left join {{ ref('dim_branches') }} b
    on bal.branch_id = b.branch_id
   and b._is_current
left join {{ ref('dim_stock_items') }} si
    on bal.stock_item_id = si.stock_item_id
   and si._is_current
left join {{ ref('dim_inventory_lots') }} l
    on bal.inventory_lot_id = l.inventory_lot_id
   and l._is_current
