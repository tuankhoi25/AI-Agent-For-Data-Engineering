{% snapshot snap_dim_allergens %}
{{
    config(
        unique_key='allergen_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_allergens', true) }} as source_rows
{% endsnapshot %}

{% snapshot snap_dim_branches %}
{{
    config(
        unique_key='branch_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_branches', true) }} as source_rows
{% endsnapshot %}

{% snapshot snap_dim_customers %}
{{
    config(
        unique_key='customer_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_customers', true) }} as source_rows
{% endsnapshot %}

{% snapshot snap_dim_employees %}
{{
    config(
        unique_key='employee_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_employees', true) }} as source_rows
{% endsnapshot %}

{% snapshot snap_dim_inventory_lots %}
{{
    config(
        unique_key='inventory_lot_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_inventory_lots', true) }} as source_rows
{% endsnapshot %}

{% snapshot snap_dim_product_categories %}
{{
    config(
        unique_key='category_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_product_categories', true) }} as source_rows
{% endsnapshot %}

{% snapshot snap_dim_products %}
{{
    config(
        unique_key='product_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_products', true) }} as source_rows
{% endsnapshot %}

{% snapshot snap_dim_promotions %}
{{
    config(
        unique_key='promotion_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_promotions', true) }} as source_rows
{% endsnapshot %}

{% snapshot snap_dim_recipes %}
{{
    config(
        unique_key='recipe_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_recipes', true) }} as source_rows
{% endsnapshot %}

{% snapshot snap_dim_stock_items %}
{{
    config(
        unique_key='stock_item_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_stock_items', true) }} as source_rows
{% endsnapshot %}

{% snapshot snap_dim_suppliers %}
{{
    config(
        unique_key='supplier_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_suppliers', true) }} as source_rows
{% endsnapshot %}

{% snapshot snap_dim_units_of_measure %}
{{
    config(
        unique_key='uom_id',
        strategy='timestamp',
        updated_at='_source_last_updated_at',
        invalidate_hard_deletes=False
    )
}}
select * from {{ latest_source_rows('stg_units_of_measure', true) }} as source_rows
{% endsnapshot %}
