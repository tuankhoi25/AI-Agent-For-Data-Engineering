{{ config(description='Staging copy of bakery.purchase_order_items.') }}

{{ source_incremental('bakery', 'purchase_order_items') }}
