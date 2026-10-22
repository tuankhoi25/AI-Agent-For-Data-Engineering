{{ config(description='Staging copy of bakery.payments.') }}

{{ source_incremental('bakery', 'payments') }}
