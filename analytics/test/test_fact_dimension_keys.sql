{{ config(tags=['quality', 'scd2', 'sales']) }}

{% set links = [
    ('fct_sales', 'sale_id', 'dim_branches', 'branch_id', 'branch_id', 'branch_sk', false),
    ('fct_sales', 'sale_id', 'dim_customers', 'customer_id', 'customer_id', 'customer_sk', true),
    ('fct_sales', 'sale_id', 'dim_employees', 'cashier_id', 'employee_id', 'employee_sk', false),
    ('fct_sale_items', 'sale_item_id', 'dim_branches', 'branch_id', 'branch_id', 'branch_sk', false),
    ('fct_sale_items', 'sale_item_id', 'dim_customers', 'customer_id', 'customer_id', 'customer_sk', true),
    ('fct_sale_items', 'sale_item_id', 'dim_products', 'product_id', 'product_id', 'product_sk', false),
    ('fct_sale_items', 'sale_item_id', 'dim_units_of_measure', 'uom_id', 'uom_id', 'uom_sk', false)
] %}

{% for fact, fact_key, dimension, fact_bk, dim_bk, sk, nullable in links %}
select '{{ fact }}' as fact_name, f.{{ fact_key }}::text as fact_key,
       '{{ dimension }}' as dimension_name, f.{{ sk }} as surrogate_key
from {{ ref(fact) }} f
left join {{ ref(dimension) }} d on f.{{ sk }} = d.{{ sk }}
where {% if nullable %}f.{{ fact_bk }} is not null and{% endif %} (
       d.{{ sk }} is null
    or f.{{ fact_bk }} is distinct from d.{{ dim_bk }}
    or f.sale_occurred_at < d._valid_from
    or f.sale_occurred_at >= coalesce(d._valid_to, 'infinity'::timestamptz)
)
{% if not loop.last %}union all{% endif %}
{% endfor %}
