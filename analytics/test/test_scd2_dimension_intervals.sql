{{ config(tags=['quality', 'scd2']) }}

{% set dimensions = [
    ('dim_allergens', 'allergen_id'), ('dim_branches', 'branch_id'),
    ('dim_customers', 'customer_id'), ('dim_employees', 'employee_id'),
    ('dim_inventory_lots', 'inventory_lot_id'), ('dim_product_categories', 'category_id'),
    ('dim_products', 'product_id'), ('dim_promotions', 'promotion_id'),
    ('dim_recipes', 'recipe_id'), ('dim_stock_items', 'stock_item_id'),
    ('dim_suppliers', 'supplier_id'), ('dim_units_of_measure', 'uom_id')
] %}

with versions as (
    {% for dimension, business_key in dimensions %}
    select
        '{{ dimension }}' as dimension_name,
        {{ business_key }}::text as business_key,
        _valid_from, _valid_to, _observed_from, _is_current,
        lead(_valid_from) over (
            partition by {{ business_key }} order by _valid_from
        ) as next_valid_from
    from {{ ref(dimension) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)
select * from versions
where _valid_to <= _valid_from
   or _is_current is distinct from (_valid_to is null)
   or _valid_to is distinct from next_valid_from
   or _observed_from < _valid_from
   or _observed_from is null
