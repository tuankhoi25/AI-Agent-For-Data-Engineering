{{ config(
    description='Purchase-order-line fulfillment. Quantities are compared only when ordered and received units match.',
    pre_hook="{{ delete_affected_mart_rows('mart_procurement_status') }}"
) }}

with changed_keys as (
    {{ mart_changed_keys('mart_procurement_status') }}
),
receipts as (
    select
        gri.purchase_order_item_id,
        sum(gri.received_quantity) filter (
            where gri.purchase_order_item_id is not null
              and gri.ordered_uom_id = gri.uom_id
        ) as received_quantity_same_uom,
        count(*) filter (
            where gri.purchase_order_item_id is not null
              and gri.ordered_uom_id is distinct from gri.uom_id
        ) as unit_mismatch_receipt_line_count,
        sum(gri.actual_line_amount) as actual_received_amount,
        max(gri._record_updated_at) as receipt_record_updated_at
    from {{ ref('core_goods_receipt_items') }} gri
    join changed_keys ck
        on gri.purchase_order_item_id is not distinct from ck.purchase_order_item_id
    where not gri._is_deleted
    group by gri.purchase_order_item_id
)

select
    poi.purchase_order_item_id,
    poi.purchase_order_id,
    poi.po_number,
    poi.supplier_id,
    poi.supplier_code,
    poi.supplier_name,
    poi.branch_id,
    poi.branch_code,
    poi.stock_item_id,
    poi.stock_item_code,
    poi.stock_item_name,
    poi.ordered_quantity,
    poi.uom_id as ordered_uom_id,
    poi.uom_code as ordered_uom_code,
    coalesce(r.received_quantity_same_uom, 0)::numeric(38,9) as received_quantity_same_uom,
    (case
        when r.received_quantity_same_uom is null then poi.ordered_quantity
        else poi.ordered_quantity - r.received_quantity_same_uom
    end)::numeric(38,9) as remaining_quantity_same_uom,
    coalesce(r.unit_mismatch_receipt_line_count, 0) as unit_mismatch_receipt_line_count,
    poi.expected_unit_cost,
    poi.expected_line_amount,
    coalesce(r.actual_received_amount, 0)::numeric(38,9) as actual_received_amount,
    poi.currency_code,
    poi.ordered_at,
    poi.expected_at,
    poi.purchase_order_status,
    greatest(
        poi._record_updated_at,
        coalesce(r.receipt_record_updated_at, poi._record_updated_at)
    ) as _record_updated_at
from {{ ref('core_purchase_order_items') }} poi
join changed_keys ck
    on poi.purchase_order_item_id is not distinct from ck.purchase_order_item_id
left join receipts r
    on poi.purchase_order_item_id is not distinct from r.purchase_order_item_id
where not poi._is_deleted
