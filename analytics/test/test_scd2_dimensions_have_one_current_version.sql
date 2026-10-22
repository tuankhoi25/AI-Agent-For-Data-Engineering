{{ config(tags=['quality', 'scd2']) }}

{% set dimensions = [
    ('dim_allergens', 'allergen_id'), ('dim_branches', 'branch_id'),
    ('dim_customers', 'customer_id'), ('dim_employees', 'employee_id'),
    ('dim_inventory_lots', 'inventory_lot_id'), ('dim_product_categories', 'category_id'),
    ('dim_products', 'product_id'), ('dim_promotions', 'promotion_id'),
    ('dim_recipes', 'recipe_id'), ('dim_stock_items', 'stock_item_id'),
    ('dim_suppliers', 'supplier_id'), ('dim_units_of_measure', 'uom_id')
] %}

{% for dimension, business_key in dimensions %}
select
    '{{ dimension }}' as dimension_name,
    {{ business_key }}::text as business_key,
    count(*) filter (where _is_current) as current_count
from {{ ref(dimension) }}
group by {{ business_key }}
having count(*) filter (where _is_current) <> 1
{% if not loop.last %}union all{% endif %}
{% endfor %}
