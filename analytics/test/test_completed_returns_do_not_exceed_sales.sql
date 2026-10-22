{{ config(tags=['quality', 'returns']) }}

select
    sale_item_id,
    sold_quantity,
    returned_quantity
from {{ ref('fct_sale_items') }}
where not _is_deleted
  and returned_quantity > sold_quantity
