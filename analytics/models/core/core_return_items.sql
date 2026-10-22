{{ config(description='Return-line grain, preserving the original sale-line relationship and restock flag.') }}

with source_rows as (
    {{ core_source_rows('stg_return_items', 'core_return_items') }}
)

select
    ri.return_item_id,
    ri.return_id,
    r.return_number,
    r.sale_id,
    r.receipt_number,
    r.branch_id,
    r.return_business_date,
    r.status as return_status,
    r.is_completed_return,
    ri.sale_item_id,
    si.product_id,
    si.sku,
    si.product_name_snapshot,
    si.uom_code,
    ri.quantity,
    ri.restockable,
    ri.refund_amount,
    ri.notes,
    ri._created_at,
    ri._last_updated_at,
    ri._is_deleted,
    ri._deleted_at
    {{ core_metadata_columns('ri', ['r', 'si']) }}
from source_rows ri
left join {{ ref('core_returns') }} r
    on ri.return_id = r.return_id
left join {{ ref('core_sale_items') }} si
    on ri.sale_item_id = si.sale_item_id
