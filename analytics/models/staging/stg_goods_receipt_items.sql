{{ config(description='Staging copy of bakery.goods_receipt_items.') }}

{{ source_incremental('bakery', 'goods_receipt_items') }}
