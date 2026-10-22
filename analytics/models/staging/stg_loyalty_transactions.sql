{{ config(description='Staging copy of bakery.loyalty_transactions.') }}

{{ source_incremental('bakery', 'loyalty_transactions') }}
