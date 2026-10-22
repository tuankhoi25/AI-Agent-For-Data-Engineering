{{ config(
    description='Daily product sales at branch/product grain. Original sold and returned quantities remain distinct.',
    pre_hook="{{ delete_affected_mart_rows('mart_product_sales') }}"
) }}

with changed_keys as (
    {{ mart_changed_keys('mart_product_sales') }}
)

select
    f.business_date,
    f.branch_id,
    max(f.branch_code) as branch_code,
    max(f.branch_name) as branch_name,
    f.product_id,
    max(f.sku) as sku,
    max(f.product_name) as product_name,
    max(f.category_code) as category_code,
    max(f.category_name) as category_name,
    max(f.product_type) as product_type,
    f.uom_code,
    sum(f.sold_quantity)::numeric(38,9) as sold_quantity,
    sum(f.returned_quantity)::numeric(38,9) as returned_quantity,
    sum(f.net_quantity)::numeric(38,9) as net_quantity,
    sum(f.gross_line_amount)::numeric(38,9) as gross_sales,
    sum(f.discount_amount)::numeric(38,9) as line_discount_amount,
    sum(f.line_total)::numeric(38,9) as net_line_sales_before_refund,
    sum(f.refund_amount)::numeric(38,9) as refund_amount,
    sum(f.net_line_sales_after_refund)::numeric(38,9) as net_line_sales_after_refund,
    count(distinct f.sale_id) as order_count,
    count(*) as sale_line_count,
    max(f._record_updated_at) as _record_updated_at
from {{ ref('fct_sale_items') }} f
join changed_keys ck
    on f.business_date is not distinct from ck.business_date
   and f.branch_id is not distinct from ck.branch_id
   and f.product_id is not distinct from ck.product_id
   and f.uom_code is not distinct from ck.uom_code
where not f._is_deleted
  and f.is_sale_completed
group by f.business_date, f.branch_id, f.product_id, f.uom_code
