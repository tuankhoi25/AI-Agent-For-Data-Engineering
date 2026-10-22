{{ config(description='Staging copy of bakery.purchase_orders.') }}

{{ source_incremental('bakery', 'purchase_orders') }}
