{{ config(tags=['quality', 'inventory']) }}

select
    stock_movement_id,
    movement_type,
    quantity_delta
from {{ ref('core_stock_movements') }}
where not _is_deleted
  and (
      (
        movement_type in ('PURCHASE_RECEIPT', 'PRODUCTION_OUTPUT', 'RETURN_IN', 'TRANSFER_IN', 'ADJUSTMENT_IN')
        and quantity_delta <= 0
    )
   or (
        movement_type in ('PRODUCTION_CONSUMPTION', 'SALE', 'WASTE', 'TRANSFER_OUT', 'ADJUSTMENT_OUT')
        and quantity_delta >= 0
    )
  )
