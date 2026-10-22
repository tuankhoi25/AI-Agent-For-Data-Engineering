{{ config(tags=['quality', 'sales']) }}

with line_totals as (
    select
        sale_id,
        sum(line_total) as line_total
    from {{ ref('fct_sale_items') }}
    where not _is_deleted
    group by sale_id
)

select
    s.sale_id,
    s.receipt_number,
    s.total_amount,
    s.tax_total,
    lt.line_total
from {{ ref('fct_sales') }} s
join line_totals lt
    on s.sale_id = lt.sale_id
where s.is_sale_completed
  and not s._is_deleted
  and abs(lt.line_total - (s.total_amount - s.tax_total)) > 0.01
