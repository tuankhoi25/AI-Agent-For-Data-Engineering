{{ config(description='Sales-line fact at one row per sale item, with partial returns aggregated by original sale line.') }}

with changed_keys as (
    {% if is_incremental() %}
        {{ changed_keys_with_watermark('sale_item_id', ['core_sale_items', 'core_return_items']) }}
    {% else %}
        select sale_item_id, null::timestamptz as changed_record_updated_at
        from {{ ref('core_sale_items') }}
    {% endif %}
),
return_totals as (
    select
        r.sale_item_id,
        sum(r.quantity) filter (where r.is_completed_return) as returned_quantity,
        sum(r.quantity) filter (where r.is_completed_return and r.restockable) as restocked_quantity,
        sum(r.refund_amount) filter (where r.is_completed_return) as refund_amount,
        max(r._record_updated_at) as return_record_updated_at
    from {{ ref('core_return_items') }} r
    join changed_keys ck
        on r.sale_item_id = ck.sale_item_id
    where not r._is_deleted
    group by r.sale_item_id
)

select
    si.sale_item_id,
    si.sale_id,
    si.receipt_number,
    si.branch_id,
    b_dim.branch_sk,
    coalesce(b_dim.branch_code, si.branch_code) as branch_code,
    coalesce(b_dim.branch_name, si.branch_name) as branch_name,
    si.customer_id,
    c_dim.customer_sk,
    si.business_date,
    si.sale_occurred_at,
    si.channel,
    si.sale_status,
    si.product_id,
    p_dim.product_sk,
    coalesce(p_dim.sku, si.sku) as sku,
    coalesce(p_dim.product_name, si.product_name) as product_name,
    coalesce(p_dim.category_code, si.category_code) as category_code,
    coalesce(p_dim.category_name, si.category_name) as category_name,
    coalesce(p_dim.product_type, si.product_type) as product_type,
    si.quantity as sold_quantity,
    si.uom_id,
    u_dim.uom_sk,
    coalesce(u_dim.uom_code, si.uom_code) as uom_code,
    si.product_name_snapshot,
    si.unit_price,
    si.gross_line_amount,
    si.discount_amount,
    si.line_total,
    coalesce(rt.returned_quantity, 0)::numeric(38,9) as returned_quantity,
    coalesce(rt.restocked_quantity, 0)::numeric(38,9) as restocked_quantity,
    coalesce(rt.refund_amount, 0)::numeric(38,9) as refund_amount,
    (si.quantity - coalesce(rt.returned_quantity, 0))::numeric(38,9) as net_quantity,
    (si.line_total - coalesce(rt.refund_amount, 0))::numeric(38,9) as net_line_sales_after_refund,
    si.is_sale_completed,
    si._created_at,
    si._last_updated_at,
    si._is_deleted,
    si._deleted_at,
    greatest(
        si._record_updated_at,
        coalesce(rt.return_record_updated_at, si._record_updated_at),
        coalesce(ck.changed_record_updated_at, si._record_updated_at)
    ) as _record_updated_at
from {{ ref('core_sale_items') }} si
join changed_keys ck
    on si.sale_item_id = ck.sale_item_id
left join return_totals rt
    on si.sale_item_id = rt.sale_item_id
left join {{ ref('dim_branches') }} b_dim
    on si.branch_id = b_dim.branch_id
   and si.sale_occurred_at >= b_dim._valid_from
   and si.sale_occurred_at < coalesce(b_dim._valid_to, '9999-12-31'::timestamptz)
left join {{ ref('dim_customers') }} c_dim
    on si.customer_id = c_dim.customer_id
   and si.sale_occurred_at >= c_dim._valid_from
   and si.sale_occurred_at < coalesce(c_dim._valid_to, '9999-12-31'::timestamptz)
left join {{ ref('dim_products') }} p_dim
    on si.product_id = p_dim.product_id
   and si.sale_occurred_at >= p_dim._valid_from
   and si.sale_occurred_at < coalesce(p_dim._valid_to, '9999-12-31'::timestamptz)
left join {{ ref('dim_units_of_measure') }} u_dim
    on si.uom_id = u_dim.uom_id
   and si.sale_occurred_at >= u_dim._valid_from
   and si.sale_occurred_at < coalesce(u_dim._valid_to, '9999-12-31'::timestamptz)
