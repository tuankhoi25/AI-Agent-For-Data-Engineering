{{ config(description='Staging copy of bakery.goods_receipts.') }}

{{ source_incremental('bakery', 'goods_receipts') }}
