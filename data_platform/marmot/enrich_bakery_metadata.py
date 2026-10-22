#!/usr/bin/env python3
"""Enrich the synced bakery catalog in Marmot with business metadata.

The script is safe to rerun: it merges asset tags/metadata, upserts glossary
terms and data products by name, and adds only missing product memberships.
It also removes legacy generator-run metadata from the operational catalog.
All project-authored catalog content is maintained in English. Rerunning the
script replaces earlier descriptions in another language, including column
descriptions and UI documentation pages. PostgreSQL records are not modified.
It reads MARMOT_HOST and MARMOT_API_KEY from the project-root .env file.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shlex
import sys
from uuid import uuid4
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from bakery_metadata_details import (
    COLUMN_DETAILS, COMMON_DETAILS, ENUM_MEANINGS, METRIC_TERMS, TABLE_RULES, ROW_AUDIT_POLICY,
    TERM_TABLES,
    schema_contracts, validate_details,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
API_PREFIX = "/api/v1"
METADATA_MARKER = "bakery_metadata_enrichment"
ENRICHMENT_PIPELINE = "bakery-metadata-enrichment"
ENRICHMENT_SOURCE = "bakery-metadata-enrichment"
ENRICHMENT_VERSION = "2.2"

# Asset.schema is a map of schema-name -> schema-content, NOT arbitrary
# metadata. Marmot renders/parses every entry as a separate schema section.
# Remove the invalid sections written by earlier enrichment versions.
LEGACY_SCHEMA_METADATA_KEYS = frozenset({
    "description", "business_rules", "declared_constraints", "definition_source",
})

# Currency context is recorded at column level so it appears in Marmot's
# Schema Content and UI documentation. Seeded bakery operations use VND;
# fields with an explicit currency_code are described relative to that column.
COLUMN_CURRENCY_CONTEXT = {
    ("products", "unit_price"): "VND (Vietnamese đồng) per selling unit",
    ("supplier_products", "last_known_unit_cost"): "the row's currency_code (currently VND by default), per stock item unit",
    ("purchase_order_items", "expected_unit_cost"): "the parent purchase order's currency_code (seeded orders use VND), per ordered unit",
    ("goods_receipt_items", "actual_unit_cost"): "the linked purchase order's currency_code when available (seeded bakery values use VND), per received unit",
    ("inventory_lots", "unit_cost"): "VND (Vietnamese đồng) per stock item base unit",
    ("stock_movements", "unit_cost"): "VND (Vietnamese đồng) per stock item unit",
    ("production_consumptions", "unit_cost"): "VND (Vietnamese đồng) per consumed stock item unit",
    ("promotions", "minimum_order_amount"): "VND (Vietnamese đồng)",
    ("sales", "subtotal"): "VND (Vietnamese đồng)",
    ("sales", "discount_total"): "VND (Vietnamese đồng)",
    ("sales", "tax_total"): "VND (Vietnamese đồng)",
    ("sales", "total_amount"): "VND (Vietnamese đồng)",
    ("sale_items", "unit_price"): "VND (Vietnamese đồng) per selling unit",
    ("sale_items", "discount_amount"): "VND (Vietnamese đồng)",
    ("sale_items", "line_total"): "VND (Vietnamese đồng)",
    ("sale_promotions", "discount_amount"): "VND (Vietnamese đồng)",
    ("payments", "amount"): "the row's currency_code (generated bakery payments use VND)",
    ("returns", "refund_total"): "VND (Vietnamese đồng)",
    ("return_items", "refund_amount"): "VND (Vietnamese đồng)",
    ("shifts", "opening_cash"): "VND (Vietnamese đồng)",
    ("shifts", "counted_cash"): "VND (Vietnamese đồng)",
    ("cash_movements", "amount"): "VND (Vietnamese đồng)",
}


def table(
    title: str,
    description: str,
    grain: str,
    domain: str,
    process: str,
    relationships: str,
    tags: tuple[str, ...] = (),
    terms: tuple[str, ...] = (),
    sensitivity: str = "internal",
    note: str = "",
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "grain": grain,
        "domain": domain,
        "process": process,
        "relationships": relationships,
        "tags": tags,
        "terms": terms,
        "sensitivity": sensitivity,
        "note": note,
    }


COLUMN_REFERENCE_LABELS = {
    "allergen_id": "allergen",
    "branch_id": "branch",
    "cashier_id": "cashier employee",
    "category_id": "product category",
    "created_by": "employee who created the transaction",
    "customer_id": "customer",
    "employee_id": "employee",
    "inventory_lot_id": "inventory lot",
    "parent_category_id": "parent category",
    "payment_id": "payment transaction",
    "product_id": "product",
    "production_batch_id": "production batch",
    "promotion_id": "promotion",
    "purchase_order_id": "purchase order",
    "purchase_order_item_id": "purchase order line",
    "recipe_id": "recipe",
    "recorded_by": "employee who recorded the transaction",
    "received_by": "receiving employee",
    "processed_by": "processing employee",
    "produced_by": "production employee",
    "sale_id": "sales receipt",
    "sale_item_id": "sales receipt line",
    "shift_id": "work shift",
    "stock_item_id": "stock item",
    "supplier_id": "supplier",
    "uom_id": "unit of measure",
    "base_uom_id": "base inventory unit",
    "sell_uom_id": "selling unit",
    "purchase_uom_id": "purchasing unit",
    "pack_uom_id": "packaging unit",
    "yield_uom_id": "recipe yield unit",
}

COLUMN_SEMANTICS = {
    "address": "Contact address or operating location",
    "applied_at": "Time at which the promotion was applied to the sales receipt",
    "batch_number": "Business identifier of the production batch",
    "category_code": "Product category code",
    "category_name": "Product category name",
    "customer_code": "Customer profile code",
    "description": "Descriptive details of the reference entity or transaction",
    "item_type": "Stock item classification, such as ingredient, packaging, finished good, or retail good",
    "joined_at": "Time at which the customer joined the loyalty program",
    "last_known_unit_cost": "Most recently recorded reference unit cost from the supplier",
    "manufactured_at": "Inventory lot manufacturing date",
    "occurred_at": "Time at which the ledger movement occurred",
    "planned_quantity": "Planned output quantity of the production batch in the associated unit",
    "produced_quantity": "Actual output quantity of the production batch in the associated unit",
    "product_name": "Product display name in the menu",
    "receipt_number": "Business identifier of the sales receipt or goods receipt",
    "recipe_version": "Version identifier of the production recipe",
    "recorded_at": "Time at which the waste event was recorded",
    "shift_code": "Business identifier of the employee shift",
    "terminated_on": "Employee employment end date, if applicable",
    "track_expiry": "Whether expiration dates are tracked for this stock item",
    "track_lot": "Whether inventory lots are tracked for this stock item",
    "actual_unit_cost": "Actual unit cost when goods are received",
    "amount": "Monetary amount of the transaction",
    "allergen_code": "Allergen code",
    "allergen_name": "Allergen name",
    "available_from": "First date on which the product is available for sale",
    "available_to": "Last date on which the product is available for sale",
    "brand_name": "Brand of the goods supplied by the supplier",
    "branch_code": "Branch code used in operations",
    "branch_name": "Branch name",
    "channel": "Sales channel through which the transaction originated",
    "close_at": "Time at which the transaction was closed",
    "closed_at": "Time at which the shift was closed",
    "completed_at": "Time at which the transaction or operation was completed",
    "coupon_code": "Coupon code applied to the sale",
    "country_code": "ISO 3166-1 alpha-2 country code",
    "created_at": "Time at which the record was created",
    "created_by": "Employee who created the transaction",
    "currency_code": "ISO 4217 currency code for associated monetary amounts; seeded and default bakery operations use VND",
    "counted_cash": "Cash counted at shift closure",
    "date_of_birth": "Customer date of birth; personal data",
    "dimension": "Measurement dimension: mass, volume, count, or length",
    "discount_amount": "Discount amount applied to the line or transaction",
    "discount_total": "Total discount amount on the sales receipt",
    "discount_value": "Configured promotion discount; its unit depends on promotion_type: percent for PERCENT and VND for FIXED_AMOUNT",
    "email": "Contact email address",
    "effective_from": "First date on which the recipe version is effective",
    "effective_to": "Last date on which the recipe version is effective",
    "employee_code": "Employee code",
    "ends_at": "Time at which the promotion expires",
    "expected_at": "Expected goods receipt time",
    "expected_unit_cost": "Expected unit cost on the purchase order",
    "expires_at": "Inventory lot expiration date",
    "full_name": "Full name",
    "hired_on": "Employee employment start date",
    "idempotency_key": "Key used to prevent duplicates when the same transaction is submitted again",
    "ingredient_summary": "Summary of the main ingredients displayed for the product",
    "instructions": "Recipe preparation instructions",
    "is_active": "Whether the reference record or entity is currently in use",
    "is_base_unit": "Whether this is the base unit for the measurement dimension",
    "is_confirmed": "Whether the relationship information has been verified",
    "is_optional": "Whether the ingredient may be omitted from the recipe",
    "line_total": "Sales receipt line amount after adjustments",
    "lot_code": "Internal lot code used for inventory traceability",
    "loyalty_transaction_id": "Unique identifier of the loyalty points transaction",
    "marketing_consent": "Customer preference indicating permission to receive marketing communications",
    "max_uses": "Maximum number of times the promotion may be used",
    "minimum_order_amount": "Minimum order amount required to qualify for the promotion",
    "movement_type": "Type of operation that increases or decreases inventory",
    "notes": "Additional notes for the transaction or reference record",
    "opening_cash": "Cash in the drawer at shift opening",
    "opening_date": "Date on which the branch began operating",
    "opened_at": "Time at which the shift or sales receipt was opened",
    "ordered_at": "Time at which the purchase order was submitted",
    "ordered_quantity": "Quantity of the stock item ordered",
    "pack_size": "Number of base units contained in one package",
    "paid_at": "Time at which payment was recorded",
    "parent_category_id": "Parent category in the product category hierarchy",
    "payment_method": "Payment method used",
    "phone": "Contact phone number; may contain personal data",
    "points_delta": "Signed change in loyalty points; negative values represent redemption or downward adjustment",
    "po_number": "Business identifier uniquely identifying the purchase order",
    "product_name_snapshot": "Product name captured at the time of sale",
    "product_type": "Type of product sold or managed",
    "promotion_code": "Promotion code",
    "promotion_name": "Promotion name",
    "promotion_type": "Promotion benefit mechanism",
    "provider_reference": "Reference identifier from the payment gateway or payment provider",
    "quantity": "Quantity recorded in the associated unit of measure",
    "quantity_delta": "Signed inventory change; the sign indicates an increase or decrease",
    "quantity_used": "Actual quantity of an ingredient consumed in production",
    "reason": "Explanation of the return or refund reason",
    "reason_code": "Reason code classifying waste or disposal",
    "received_at": "Time at which goods were received from the supplier",
    "received_quantity": "Actual quantity received",
    "reorder_level": "Inventory threshold that triggers replenishment",
    "restockable": "Whether returned goods qualify for restocking",
    "return_number": "Return document number",
    "returned_at": "Time at which the return was processed",
    "refund_amount": "Refund amount for the returned line",
    "refund_total": "Total refund amount on the return document",
    "role_name": "Employee job role",
    "sale_item_id": "Unique identifier of the sales receipt line",
    "sku": "SKU code identifying a saleable product",
    "source_id": "Record identifier of the originating transaction",
    "source_type": "Type of originating transaction that generated the movement",
    "started_at": "Time at which production started",
    "starts_at": "Time at which the promotion becomes effective",
    "status": "Current status of the transaction or operation",
    "stock_item_code": "Stock item code",
    "stock_item_name": "Stock item name",
    "subtotal": "Total merchandise amount before discounts and taxes",
    "supplier_code": "Supplier code",
    "supplier_invoice_number": "Invoice number issued by the supplier",
    "supplier_lot_code": "Lot code provided by the supplier",
    "supplier_name": "Supplier name",
    "supplier_sku": "Item code in the supplier catalog",
    "supplier_type": "Supplier classification by the type of goods supplied",
    "tax_total": "Total tax amount on the sales receipt",
    "timezone": "Time zone used for branch operating schedules",
    "total_amount": "Total amount payable by the customer",
    "transaction_type": "Type of loyalty points movement",
    "unit_cost": "Unit cost of the stock item at the time of the transaction",
    "unit_price": "Product selling price per unit",
    "uom_code": "Unit of measure code",
    "uom_name": "Unit of measure name",
    "website": "Supplier website",
    "yield_quantity": "Expected finished product output from one recipe batch",
}


COLUMN_SEMANTICS.update(COMMON_DETAILS)

# Descriptions and relationships are grounded in the project's SQL schema.
ASSETS: dict[str, dict[str, Any]] = {
    'branches': table(
        'Store branches',
        'Reference list of bakery retail locations, including code, address, time zone, opening date, and active status.',
        'One row per branch.',
        'store_operations',
        'Manage stores and the locations where transactions originate.',
        'Referenced by employees, purchase orders, goods receipts, inventory, production, sales, shifts, and cash movements.',
        ('master-data', 'store-operations'),
        ('Bakery: Branch',),
    ),
    'product_categories': table(
        'Product categories',
        'Category hierarchy used to classify French pastries, beverages, retail goods, and merchandise on the menu and POS.',
        'One row per category; parent_category_id defines the parent-child relationship.',
        'product_catalog',
        'Organize the menu and analyze sales by product group.',
        'products.category_id references the category; parent_category_id references this table.',
        ('master-data', 'product-catalog'),
        ('Bakery: Product Category', 'Bakery: Product'),
    ),
    'units_of_measure': table(
        'Units of measure',
        'Reference list of mass, volume, count, and length units used consistently in recipes and inventory.',
        'One row per unit of measure.',
        'inventory',
        'Standardize quantities purchased, produced, consumed, and sold.',
        'Referenced by stock_items, products, recipes, recipe_items, purchase_order_items, goods receipt lines, and stock movements.',
        ('master-data', 'inventory'),
        ('Bakery: Unit of Measure',),
    ),
    'suppliers': table(
        'Suppliers',
        'Reference list of suppliers of ingredients, packaging, coffee, and takeaway retail goods, including supplier type and contact information.',
        'One row per supplier.',
        'procurement',
        'Manage supply sources and contact information used for purchasing.',
        'Linked to supplier_products, purchase_orders, and goods_receipts.',
        ('master-data', 'procurement'),
        ('Bakery: Supplier', 'Bakery: Purchase Order'),
        note='Supplier details, websites, and addresses are illustrative seed data for this project.',
    ),
    'customers': table(
        'Customers and loyalty members',
        'Customer profiles created when a transaction requires customer identification or loyalty points, including contact details, enrollment date, and marketing preferences.',
        'One row per customer profile.',
        'sales_customer',
        'Support purchase history, customer service, and the loyalty program.',
        'Referenced by sales and loyalty_transactions.',
        ('customer-data', 'loyalty', 'contains-pii'),
        ('Bakery: Customer', 'Bakery: Loyalty Points'),
        sensitivity='personal',
        note='May contain names, phone numbers, email addresses, and dates of birth. marketing_consent records the marketing preference; false does not indicate consent.',
    ),
    'employees': table(
        'Store employees',
        'Reference list of employees, roles, and employment dates, used to identify the staff responsible for operational transactions.',
        'One row per employee.',
        'store_operations',
        'Assign staff and trace responsibility for sales, shifts, goods receipts, production, refunds, and cash handling.',
        'References branches; referenced by sales, goods_receipts, purchase_orders, production_batches, returns, waste_records, shifts, and cash_movements.',
        ('workforce', 'store-operations', 'contains-pii'),
        ('Bakery: Employee', 'Bakery: Branch'),
        sensitivity='personal',
        note='Contains employee names, roles, and phone numbers; intended for internal operations.',
    ),
    'allergens': table(
        'Allergen reference list',
        'Standard reference list of allergens used to describe ingredients that may be present in products.',
        'One row per allergen.',
        'food_safety',
        'Standardize ingredient declarations and support allergen information lookup.',
        'Linked to products through product_allergens.',
        ('food-safety', 'master-data'),
        ('Bakery: Allergen', 'Bakery: Product'),
    ),
    'stock_items': table(
        'Stock item catalog',
        'Catalog of ingredients, packaging, finished goods, and retail goods tracked in inventory, including base units and lot/expiration tracking rules.',
        'One row per stock item.',
        'inventory',
        'Identify items purchased, consumed, produced, sold, returned, or discarded.',
        'Linked to units_of_measure; referenced by supplier_products, recipes, purchase orders, lots, movements, production, product inventory mappings, and waste records.',
        ('inventory', 'master-data'),
        ('Bakery: Stock Item', 'Bakery: Unit of Measure', 'Bakery: Inventory Lot'),
    ),
    'products': table(
        'Menu and saleable products',
        'Catalog of goods sold at the bakery: French pastries, beverages, packaged takeaway products, and merchandise, including SKU, category, price, and ingredient summary.',
        'One row per saleable SKU.',
        'product_catalog',
        'Provide product, price, and unit information for POS, production, and sales reporting.',
        'Linked to product_categories and units_of_measure, and associated with stock_items, recipes, allergens, promotions, sale_items, and production_batches.',
        ('product-catalog', 'sales', 'menu'),
        ('Bakery: Product', 'Bakery: Product Category', 'Bakery: Allergen'),
        note='ingredient_summary is a summary; recipes and recipe_items contain the quantitative recipe structure.',
    ),
    'supplier_products': table(
        'Supplier item catalog',
        'Links suppliers to the stock items they supply, including supplier SKU, brand, purchase packaging, and reference unit cost.',
        'One row per supplier and stock item pair.',
        'procurement',
        'Compare supply sources, purchase packaging, and costs for ingredients, packaging, and retail goods.',
        'Links suppliers, stock_items, and purchasing/packaging units in units_of_measure.',
        ('procurement', 'supplier-catalog'),
        ('Bakery: Supplier', 'Bakery: Stock Item'),
        note='last_known_unit_cost is a reference cost and is not necessarily a current quotation.',
    ),
    'product_allergens': table(
        'Product allergen relationships',
        'Links products to relevant allergens, including a verification flag and notes about the source or interpretation.',
        'One row per product and allergen pair.',
        'food_safety',
        'Look up and review allergen risks in the menu.',
        'Links products to allergens; is_confirmed indicates whether the relationship has been verified.',
        ('food-safety', 'product-catalog'),
        ('Bakery: Product', 'Bakery: Allergen'),
        note='is_confirmed=false does not mean the product is free of the allergen.',
    ),
    'recipes': table(
        'Production recipes',
        'Recipe versions for products, including batch yield, unit of measure, effective dates, and preparation instructions.',
        'One row per recipe version for a product.',
        'production',
        'Standardize quantities and preparation instructions for pastries and beverages by recipe version.',
        'Links products and units_of_measure; referenced by recipe_items and production_batches.',
        ('production', 'recipe-management'),
        ('Bakery: Recipe', 'Bakery: Product', 'Bakery: Stock Item'),
    ),
    'recipe_items': table(
        'Recipe ingredients',
        'Quantity of each ingredient or material used in a recipe version, with optional ingredient flags.',
        'One row per ingredient in a recipe.',
        'production',
        'Calculate ingredient requirements and compare them with actual production consumption.',
        'Links recipes, stock_items, and units_of_measure.',
        ('production', 'recipe-management', 'inventory'),
        ('Bakery: Recipe', 'Bakery: Stock Item', 'Bakery: Unit of Measure'),
    ),
    'purchase_orders': table(
        'Supplier purchase orders',
        'Purchase order headers for ingredients and goods: supplier, receiving branch, order time, status, and currency.',
        'One row per purchase order.',
        'procurement',
        'Track the purchase order lifecycle from draft or submission to full receipt or cancellation.',
        'Links suppliers, branches, and the employee who created the order; referenced by purchase_order_items and goods_receipts.',
        ('procurement', 'inventory'),
        ('Bakery: Purchase Order', 'Bakery: Supplier', 'Bakery: Branch'),
    ),
    'purchase_order_items': table(
        'Purchase order lines',
        'Items, quantities, units, and expected unit costs on each purchase order.',
        'One row per item on a purchase order.',
        'procurement',
        'Compare ordered quantities with actual receipts and expected costs.',
        'Links purchase_orders, stock_items, and units_of_measure; may be referenced by goods_receipt_items.',
        ('procurement', 'inventory'),
        ('Bakery: Purchase Order', 'Bakery: Stock Item', 'Bakery: Unit of Measure'),
    ),
    'goods_receipts': table(
        'Goods receipts',
        'Goods receipt headers recording goods received from suppliers, receiving branch, receipt time, and responsible employee.',
        'One row per goods receipt event.',
        'procurement',
        'Record actual deliveries and support creation of inventory lots and stock entries.',
        'Links purchase_orders, suppliers, branches, and employees; referenced by goods_receipt_items and inventory_lots.',
        ('procurement', 'inventory'),
        ('Bakery: Goods Receipt', 'Bakery: Supplier', 'Bakery: Inventory Lot'),
    ),
    'inventory_lots': table(
        'Inventory lots',
        'Tracks ingredient and goods lots, supplier lot codes, production/receipt/expiration dates, and unit costs.',
        'One row per lot of a stock item.',
        'inventory',
        'Support source traceability, FIFO/FEFO, and expiration control.',
        'Links stock_items and goods_receipts; referenced by goods receipt lines, stock_movements, production_consumptions, and waste_records.',
        ('inventory', 'traceability', 'expiry-control'),
        ('Bakery: Inventory Lot', 'Bakery: Stock Item', 'Bakery: Goods Receipt'),
    ),
    'goods_receipt_items': table(
        'Goods receipt lines',
        'Actual quantities and costs of each item received, optionally linked to a purchase order line and inventory lot.',
        'One row per receiving line or lot allocation on a goods receipt; an item can appear on multiple lines.',
        'procurement',
        'Reconcile purchase orders, goods receipts, actual prices, and received lots.',
        'Links goods_receipts, purchase_order_items, stock_items, inventory_lots, and units_of_measure.',
        ('procurement', 'inventory'),
        ('Bakery: Goods Receipt', 'Bakery: Purchase Order', 'Bakery: Inventory Lot'),
    ),
    'stock_movements': table(
        'Inventory movement ledger',
        'Event ledger recording inventory increases and decreases by operation type, signed quantity, time, lot, and originating transaction; SQL does not enforce immutability.',
        'One row per inventory movement.',
        'inventory',
        'Trace purchases, production consumption, finished goods, sales, returns, waste, and adjustments.',
        'Links branches, stock_items, inventory_lots, units_of_measure, and employees; source_type/source_id identify the originating transaction.',
        ('inventory', 'ledger', 'traceability'),
        ('Bakery: Stock Movement', 'Bakery: Stock Item', 'Bakery: Inventory Lot'),
        note='quantity_delta is signed; inventory balances are derived from movements rather than stored as balance snapshots.',
    ),
    'production_batches': table(
        'Production batches',
        'Production plans and results by product, branch, recipe, planned/actual quantity, and batch status.',
        'One row per production batch.',
        'production',
        'Track production from planning and work in progress to completion or cancellation.',
        'Links branches, products, recipes, units_of_measure, and employees; referenced by production_consumptions.',
        ('production', 'batch-tracking'),
        ('Bakery: Production Batch', 'Bakery: Recipe', 'Bakery: Product'),
    ),
    'production_consumptions': table(
        'Ingredient consumption by batch',
        'Ingredient quantities and costs consumed by each production batch, optionally traced to a specific inventory lot.',
        'One row per batch, stock item and optional lot allocation; repeated NULL-lot allocations are permitted by SQL.',
        'production',
        'Compare standard recipe requirements with actual consumption and production costs.',
        'Links production_batches, stock_items, inventory_lots, and units_of_measure.',
        ('production', 'inventory', 'costing'),
        ('Bakery: Production Batch', 'Bakery: Stock Item', 'Bakery: Inventory Lot'),
    ),
    'promotions': table(
        'Promotions',
        'Promotion eligibility rules and validity periods for percentage discounts, fixed discounts, bundles, and loyalty redemption.',
        'One row per promotion.',
        'sales_customer',
        'Manage discount values, minimum order amounts, validity periods, and usage limits.',
        'Linked to products through promotion_products and to applied transactions through sale_promotions.',
        ('sales', 'promotion', 'pricing'),
        ('Bakery: Promotion', 'Bakery: Sale'),
    ),
    'promotion_products': table(
        'Promotion product eligibility',
        'Link table identifying the products included in each promotion.',
        'One row per promotion and product pair.',
        'sales_customer',
        'Identify items eligible for promotional benefits.',
        'Links promotions to products.',
        ('sales', 'promotion', 'product-catalog'),
        ('Bakery: Promotion', 'Bakery: Product'),
    ),
    'sales': table(
        'Sales transactions',
        'POS sales receipt headers recording branch, optional customer, cashier, sales channel, status, and transaction totals.',
        'One row per sales receipt.',
        'sales_customer',
        'Track in-store, takeaway, delivery, and online sales.',
        'Links branches, customers, and employees; referenced by sale_items, sale_promotions, payments, loyalty_transactions, returns, and cash_movements.',
        ('sales', 'pos', 'transaction'),
        ('Bakery: Sale', 'Bakery: Customer', 'Bakery: Payment', 'Bakery: Promotion'),
        note='total_amount is the sales receipt total; it is not automatically reconciled accounting revenue.',
    ),
    'sale_items': table(
        'Sales receipt lines',
        'Product lines with quantity, unit, price at the time of sale, line discount, and line amount; product_name_snapshot preserves the name at the time of the transaction.',
        'One row per product line on a sales receipt.',
        'sales_customer',
        'Analyze product quantities and sales amounts while preserving product names and prices as captured at sale time.',
        'Links sales, products, and units_of_measure; referenced by return_items.',
        ('sales', 'pos', 'transaction-detail'),
        ('Bakery: Sale', 'Bakery: Product', 'Bakery: Return'),
    ),
    'sale_promotions': table(
        'Promotions applied to sales receipts',
        'Records promotions actually applied to sales receipts, discount amounts, coupons, and application times.',
        'One row per promotion applied to a sales receipt.',
        'sales_customer',
        'Reconcile actual discounts and evaluate promotion performance.',
        'Links sales to promotions.',
        ('sales', 'promotion', 'transaction-detail'),
        ('Bakery: Sale', 'Bakery: Promotion'),
    ),
    'payments': table(
        'Payments',
        'Payment/tender records for sales receipts, including successful collections, pending or failed attempts, methods, amounts, statuses and provider references.',
        'One row per payment/tender record; a receipt can have multiple records of the same or different methods.',
        'finance',
        'Reconcile collected amounts by payment method and processing status.',
        'Links sales; indirectly related to cash_movements for cash payments.',
        ('finance', 'sales', 'payment'),
        ('Bakery: Payment', 'Bakery: Sale'),
        note='provider_reference may contain a payment reference identifier; it should not be interpreted as payment card data.',
    ),
    'loyalty_transactions': table(
        'Loyalty points transactions',
        'Ledger of points earned, redeemed, adjusted, or expired by customer and related sales receipt.',
        'One row per customer loyalty points movement.',
        'sales_customer',
        'Calculate points history and link loyalty benefits to sales transactions.',
        'Links customers and optionally sales.',
        ('loyalty', 'sales', 'customer-data'),
        ('Bakery: Loyalty Points', 'Bakery: Customer', 'Bakery: Sale'),
        sensitivity='personal',
    ),
    'returns': table(
        'Return and refund documents',
        'Return headers recording the original sale, reason, employee, status, and total refund.',
        'One row per return document.',
        'sales_customer',
        'Track complaints, returned goods, and refunds.',
        'Links sales and employees; referenced by return_items.',
        ('sales', 'returns', 'finance'),
        ('Bakery: Return', 'Bakery: Sale', 'Bakery: Employee'),
    ),
    'return_items': table(
        'Returned item lines',
        'Products and quantities returned from sales receipt lines, including refund amount and restocking eligibility.',
        'One row per returned sales receipt line.',
        'sales_customer',
        'Classify returned products, refund amounts, and goods eligible for restocking.',
        'Links returns to sale_items.',
        ('sales', 'returns', 'inventory'),
        ('Bakery: Return', 'Bakery: Sale', 'Bakery: Inventory Lot'),
    ),
    'waste_records': table(
        'Waste and disposal records',
        'Records ingredients or goods discarded due to spoilage, expiration, unsold stock, quality defects, or production loss.',
        'One row per waste event.',
        'inventory',
        'Track waste reasons, discarded quantities, related lots, branch, and recording employee.',
        'Links branches, stock_items, inventory_lots, units_of_measure, and employees.',
        ('inventory', 'waste', 'food-safety'),
        ('Bakery: Waste', 'Bakery: Stock Item', 'Bakery: Inventory Lot'),
    ),
    'shifts': table(
        'Work shifts and cash reconciliation',
        'Employee shifts at branches, including opening/closing times, opening cash, counted cash, and status.',
        'One row per employee shift.',
        'store_operations',
        'Track staffing operations and reconcile cash by shift.',
        'Links branches and employees; referenced by cash_movements.',
        ('workforce', 'store-operations', 'cash-control'),
        ('Bakery: Shift', 'Bakery: Employee', 'Bakery: Branch'),
    ),
    'cash_movements': table(
        'Cash movements by shift',
        'Cash inflows and outflows in a shift drawer, such as opening cash, cash sales, cash expenses, and refunds.',
        'One row per cash movement.',
        'finance',
        'Reconcile actual cash with sales and shift closure results.',
        'Links shifts and optionally sales and employees.',
        ('finance', 'cash-control', 'store-operations'),
        ('Bakery: Cash Movement', 'Bakery: Shift', 'Bakery: Sale'),
    ),
    'weather_daily': table(
        'Daily weather observations',
        'Detailed daily weather observations fetched from Open-Meteo for the bakery location, including temperature, apparent temperature, humidity, precipitation, daylight and wind metrics.',
        'One row per weather date, location and weather source.',
        'weather_operations',
        'Support weather-aware demand analysis and correlation with bakery sales and operations.',
        'External weather observation; linked to analytics_mart.fct_daily_weather by weather_date and source grain.',
        ('weather', 'external-source'),
        note='Weather observations are provider data, not a street-level gauge; api_fetched_at records API retrieval time.',
    ),
}


TERMS: dict[str, dict[str, Any]] = {
    "Bakery Operations": {
        "definition": "Shared business vocabulary for a French bakery data system covering pastries, beverages, and takeaway goods.",
        "description": "Root glossary group for the Bakery catalog.",
        "domain": "cross_domain",
    },
    "Bakery: Branch": {
        "definition": "A store location with a code, address, time zone, and active status; transactions and inventory or production activities may be assigned to a branch.",
        "description": "A retail branch or operational location of the bakery.",
        "domain": "store_operations",
    },
    "Bakery: Product Category": {
        "definition": "A menu or POS product classification that may be organized into a parent-child hierarchy.",
        "description": "A selling category, such as pastries, beverages, or retail goods.",
        "domain": "product_catalog",
    },
    "Bakery: Unit of Measure": {
        "definition": "A quantity unit with a MASS, VOLUME, COUNT, or LENGTH dimension, used consistently to record production and inventory quantities.",
        "description": "A base unit or transaction unit for an item.",
        "domain": "inventory",
    },
    "Bakery: Supplier": {
        "definition": "An organization supplying one or more items for bakery operations; costs and purchase packaging may vary by item and supplier.",
        "description": "A source of ingredients, packaging, beverages, or retail goods.",
        "domain": "procurement",
    },
    "Bakery: Customer": {
        "definition": "A customer profile that may be linked to sales receipts and loyalty points. Contact information is personal data and should be used according to consent preferences.",
        "description": "A customer or member of the loyalty program.",
        "domain": "sales_customer",
    },
    "Bakery: Employee": {
        "definition": "A store staff member with a role and employment status, used to trace responsibility for operational activities.",
        "description": "An employee assigned to a branch or operational activity.",
        "domain": "store_operations",
    },
    "Bakery: Allergen": {
        "definition": "A substance or ingredient group tracked because it may cause an allergic reaction. Product relationships must be verified against recipes and supplier information before being used as safety assurances.",
        "description": "A reference list of allergens associated with products.",
        "domain": "food_safety",
    },
    "Bakery: Stock Item": {
        "definition": "An item whose quantity is tracked in inventory, such as an ingredient, packaging material, finished product, or retail good.",
        "description": "An inventory item with a base unit and lot/expiration tracking settings.",
        "domain": "inventory",
    },
    "Bakery: Product": {
        "definition": "A SKU sold or produced, with a menu name, category, selling unit, price, and ingredient summary.",
        "description": "A pastry, beverage, packaged takeaway item, or merchandise product.",
        "domain": "product_catalog",
    },
    "Bakery: Recipe": {
        "definition": "A recipe version effective during a specified period that defines yield, ingredients, and quantities for producing a product.",
        "description": "A recipe or bill of materials (BOM) used in production.",
        "domain": "production",
    },
    "Bakery: Purchase Order": {
        "definition": "An order placed with a supplier, consisting of a header and item lines specifying quantities, units, and expected costs.",
        "description": "A purchase order for ingredients, packaging, or goods.",
        "domain": "procurement",
    },
    "Bakery: Goods Receipt": {
        "definition": "An operational record of goods received from a supplier; receipt lines may reference purchase order lines and inventory lots.",
        "description": "An actual delivery received by a branch or inventory location.",
        "domain": "procurement",
    },
    "Bakery: Inventory Lot": {
        "definition": "Goods grouped under a lot code to trace their receipt or production origin and expiration date.",
        "description": "An inventory unit used for traceability and expiration control.",
        "domain": "inventory",
    },
    "Bakery: Stock Movement": {
        "definition": "An event that increases or decreases inventory. quantity_delta is signed; current inventory may be calculated by aggregating the applicable movements.",
        "description": "An inventory ledger event caused by purchasing, production, sales, returns, waste, or adjustments.",
        "domain": "inventory",
    },
    "Bakery: Production Batch": {
        "definition": "One planned or executed production run for a product and recipe, with planned and actual quantities, status, and responsible employee.",
        "description": "A batch of pastries or another product.",
        "domain": "production",
    },
    "Bakery: Promotion": {
        "definition": "An offer with a discount mechanism, validity period, and eligibility rules that may restrict products or usage counts.",
        "description": "A sales promotion or loyalty points redemption offer.",
        "domain": "sales_customer",
    },
    "Bakery: Sale": {
        "definition": "A sales receipt or transaction with a branch, channel, status, and total amount; individual product lines are stored in sale_items.",
        "description": "A sales transaction header for in-store, takeaway, delivery, or online sales.",
        "domain": "sales_customer",
    },
    "Bakery: Payment": {
        "definition": "A payment linked to a sales receipt, including method, amount, status, and processing time.",
        "description": "A record of money collected through a payment method.",
        "domain": "finance",
    },
    "Bakery: Loyalty Points": {
        "definition": "A signed change in customer points due to earning, redemption, adjustment, or expiration; points_delta records the change.",
        "description": "A loyalty points ledger, rather than a balance snapshot.",
        "domain": "sales_customer",
    },
    "Bakery: Return": {
        "definition": "A return linked to the original sales receipt, including returned items, reason, restocking eligibility, and refund amount.",
        "description": "Handling of returned goods and refunds.",
        "domain": "sales_customer",
    },
    "Bakery: Waste": {
        "definition": "Ingredients or goods removed from inventory due to expiration, spoilage, quality issues, unsold stock, or production loss.",
        "description": "A record of waste and disposal.",
        "domain": "inventory",
    },
    "Bakery: Shift": {
        "definition": "An employee work and cash-handling period at a branch, from shift opening to shift closure.",
        "description": "A unit for staffing and cash reconciliation.",
        "domain": "store_operations",
    },
    "Bakery: Cash Movement": {
        "definition": "A cash inflow or outflow in the shift drawer, such as opening cash, cash sales, cash expenses, or refunds.",
        "description": "A ledger of cash changes by shift.",
        "domain": "finance",
    },
}

# Canonical and common English business wording for glossary search.
GLOSSARY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "Bakery Operations": ("Bakery", "Pastry Shop", "Bakery Operations"),
    "Bakery: Branch": ("Store Branch", "Store", "Retail Location"),
    "Bakery: Product Category": ("Menu Category", "Product Group", "Product Classification"),
    "Bakery: Unit of Measure": ("UOM", "Measurement Unit", "Quantity Unit"),
    "Bakery: Supplier": ("Vendor", "Supply Partner", "Goods Supplier"),
    "Bakery: Customer": ("Customer", "Member", "Loyalty Member"),
    "Bakery: Employee": ("Staff", "Personnel", "Store Employee"),
    "Bakery: Allergen": ("Allergenic Substance", "Allergen", "Allergenic Ingredient"),
    "Bakery: Stock Item": ("Inventory Item", "Stock Item", "Inventory SKU"),
    "Bakery: Product": ("Menu Item", "Saleable SKU", "Saleable Product"),
    "Bakery: Recipe": ("BOM", "Recipe", "Formula"),
    "Bakery: Purchase Order": ("PO", "Purchase Order", "Supplier Order"),
    "Bakery: Goods Receipt": ("Goods Receipt", "Receiving Document", "Goods Received Note"),
    "Bakery: Inventory Lot": ("Lot", "Inventory Batch", "Stock Lot"),
    "Bakery: Stock Movement": ("Inventory Transaction", "Stock Ledger", "Inventory Movement"),
    "Bakery: Production Batch": ("Production Run", "Production Batch", "Baking Batch"),
    "Bakery: Promotion": ("Discount", "Offer", "Sales Promotion"),
    "Bakery: Sale": ("Order", "POS Transaction", "Sales Receipt", "Sales Transaction"),
    "Bakery: Payment": ("Tender", "Payment", "Payment Collection"),
    "Bakery: Loyalty Points": ("Reward Points", "Member Points", "Loyalty Points"),
    "Bakery: Return": ("Refund", "Returned Goods", "Return Document"),
    "Bakery: Waste": ("Spoilage", "Inventory Loss", "Disposal", "Damaged Goods"),
    "Bakery: Shift": ("Work Shift", "Employee Shift", "Staff Shift"),
    "Bakery: Cash Movement": ("Cash Drawer Transaction", "Cash Movement", "Cash Inflow or Outflow"),
}

# Table summaries support discovery; detailed rules live on schema, metadata
# and UI pages. Reference values remain unchanged in PostgreSQL.
for _table_name, _table_spec in ASSETS.items():
    _table_spec["description"] += " " + TABLE_RULES[_table_name][0]

for _term_name, _tables in TERM_TABLES.items():
    TERMS[_term_name]["metadata"] = {
        "source_tables": list(_tables),
        "business_rules": {name: TABLE_RULES[name] for name in _tables},
    }
    TERMS[_term_name]["description"] += " Source tables: " + ", ".join(f"bakery.{name}" for name in _tables) + ". " + " ".join(TABLE_RULES[_tables[0]])

for _term_name, _term_spec in METRIC_TERMS.items():
    TERMS[_term_name] = {key: value for key, value in _term_spec.items() if key not in ("tables", "synonyms")}
    GLOSSARY_SYNONYMS[_term_name] = _term_spec["synonyms"]
    for _table_name in _term_spec["tables"]:
        ASSETS[_table_name]["terms"] += (_term_name,)

# Keep the bakery vocabulary together in the catalog. Marmot supports nested
# glossary terms; the root is created first because TERMS preserves insertion order.
for _term_name, _term_spec in TERMS.items():
    if _term_name != "Bakery Operations":
        _term_spec.setdefault("parent", "Bakery Operations")


PRODUCTS: dict[str, dict[str, Any]] = {
    "French Bakery — Sales & Loyalty": {
        "description": "Data product for analyzing the menu, sales receipts, payments, promotions, customers, and loyalty program of the French bakery. Supports transaction analysis by product, channel, and branch and evaluation of promotional offers; customer data may contain personal information.",
        "tables": (
            "branches",
            "customers",
            "product_categories",
            "products",
            "promotions",
            "promotion_products",
            "sales",
            "sale_items",
            "sale_promotions",
            "payments",
            "loyalty_transactions",
            "returns",
            "return_items",
        ),
        "tags": ("bakery", "sales", "customer-loyalty", "pos"),
        "metadata": {
            "business_domain": "sales_customer",
            "intended_audience": ["store managers", "marketing", "menu managers"],
            "grain": "A collection of reference and transaction tables; the grain of each table is described on its asset.",
            "refresh_expectation": "Metadata is synchronized on the Marmot schedule; transaction data changes as sales and loyalty activity are recorded.",
            "sensitivity": "The customers table contains personal data; restrict access as appropriate.",
            "enrichment_source": METADATA_MARKER,
        },
    },
    "French Bakery — Procurement & Inventory": {
        "description": "Data product covering suppliers, purchase orders, goods receipts, lots, expiration dates, inventory, and waste. Supports traceability from suppliers to lots and inventory movements; demonstration costs are illustrative.",
        "tables": (
            "branches",
            "suppliers",
            "supplier_products",
            "units_of_measure",
            "stock_items",
            "purchase_orders",
            "purchase_order_items",
            "goods_receipts",
            "goods_receipt_items",
            "inventory_lots",
            "stock_movements",
            "waste_records",
        ),
        "tags": ("bakery", "procurement", "inventory", "traceability"),
        "metadata": {
            "business_domain": "procurement_inventory",
            "intended_audience": ["inventory managers", "purchasing staff", "store managers"],
            "grain": "A collection of reference tables and purchase, receipt, and inventory movement events; see each asset for its grain.",
            "refresh_expectation": "Metadata follows the Marmot schedule; inventory balances are derived from the stock_movements ledger.",
            "caveat": "Costs and supplier details in the demonstration data are not current quotations.",
            "enrichment_source": METADATA_MARKER,
        },
    },
    "French Bakery — Production & Food Safety": {
        "description": "Data product for recipe management, batch production, ingredient consumption, and allergen information. Supports comparison of standard recipe requirements with production; allergen declarations must be verified against recipes and suppliers before advising customers.",
        "tables": (
            "products",
            "product_categories",
            "allergens",
            "product_allergens",
            "stock_items",
            "units_of_measure",
            "recipes",
            "recipe_items",
            "production_batches",
            "production_consumptions",
            "inventory_lots",
            "stock_movements",
            "waste_records",
        ),
        "tags": ("bakery", "production", "food-safety", "recipes"),
        "metadata": {
            "business_domain": "production_food_safety",
            "intended_audience": ["head pastry chef", "production staff", "food safety coordinator"],
            "grain": "A collection of catalog records, recipe versions, production batches, and consumption lines.",
            "refresh_expectation": "Metadata follows the Marmot schedule; production data changes as batches and ingredient consumption are recorded.",
            "caveat": "is_confirmed=false does not mean that a product is free of the allergen.",
            "enrichment_source": METADATA_MARKER,
        },
    },
    "French Bakery — Store Operations & Cash Control": {
        "description": "Data product covering branches, employees, shifts, sales, and cash drawer movements for operational checks by shift. Does not replace accounting reconciliation or payment provider records.",
        "tables": (
            "branches",
            "employees",
            "shifts",
            "sales",
            "payments",
            "cash_movements",
        ),
        "tags": ("bakery", "store-operations", "workforce", "finance"),
        "metadata": {
            "business_domain": "store_operations_finance",
            "intended_audience": ["branch managers", "cashiers", "operations finance staff"],
            "grain": "A collection of operational events; see each asset for its grain.",
            "refresh_expectation": "Metadata follows the Marmot schedule; operational data changes as shifts, payments, and cash movements are recorded.",
            "sensitivity": "The employees table contains personnel information; grant only necessary access.",
            "caveat": "Cash drawer balances require reconciliation with shift counts and payment records.",
            "enrichment_source": METADATA_MARKER,
        },
    },
}

# Surface calculation scope in the human-readable product description too;
# some Marmot MCP tools do not include arbitrary product metadata.
PRODUCT_GUIDANCE = {
    "French Bakery — Sales & Loyalty": "Keep receipt measures separate from sale-line, payment, offer and return grains. Original receipt/line amounts are retained after returns; define lifecycle and refund scope explicitly. Selling quantities are in each line's unit, not automatically individual pastries. Anonymous receipts are valid; customer coverage is not customer retention. Current amounts use VND and current tax is zero, without a general VAT policy.",
    "French Bakery — Procurement & Inventory": "Stock on hand is the signed movement balance at a cutoff, not movement count or lot count. Separate quantity on hand from usable, unexpired stock. Compare ordered, received and consumed quantities/costs only in compatible units and currencies. Purchase order, receipt, receipt-line and lot records have different grains; unknown cost is not zero. Current default procurement currency is VND.",
    "French Bakery — Production & Food Safety": "Compare actual and planned quantities only for compatible product/output units and explicit batch lifecycle scope. Consumption rows and negative inventory entries represent the same consumption. Ingredient costing excludes labor and overhead, and missing input costs make complete costing uncertain. Neither an absent allergen association nor unconfirmed status proves allergen-free food.",
    "French Bakery — Store Operations & Cash Control": "Trading begins at branches.opening_date, not the first observed receipt; use branch timezone for business dates. Derive cash direction from movement_type because stored amounts are positive. Include opening float once and exclude noncash tender. Current counted_cash is computed from the expected drawer ledger and is not an independent physical count. Amounts in this product use VND.",
}
for _product_name, _product_spec in PRODUCTS.items():
    _product_spec["description"] += " " + PRODUCT_GUIDANCE[_product_name]
    _product_spec["metadata"].update({
        "source_tables": list(_product_spec["tables"]),
        "business_rules": PRODUCT_GUIDANCE[_product_name],
        "metrics": {name: term["metadata"] for name, term in METRIC_TERMS.items() if set(term["tables"]).issubset(_product_spec["tables"])},
        "definition_sources": [schema_contracts()[name]["source"] for name in _product_spec["tables"]],
        "enrichment_version": ENRICHMENT_VERSION,
    })


def load_env_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"Missing .env file: {path}")
    raw_values: dict[str, tuple[str, bool]] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            continue
        expand = True
        if raw_value[:1] in {"'", '"'}:
            expand = raw_value.startswith('"')
            try:
                parsed = shlex.split(raw_value, posix=True)
                value = parsed[0] if parsed else ""
            except ValueError as exc:
                raise RuntimeError(f"Invalid .env value for {key}") from exc
        else:
            value = raw_value.split("#", 1)[0].strip()
        raw_values[key] = (value, expand)

    variable_pattern = re.compile(
        r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-|-)([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)"
    )
    resolved: dict[str, str] = {}

    def resolve(key: str, stack: set[str]) -> str | None:
        if key in os.environ:
            return os.environ[key]
        if key in resolved:
            return resolved[key]
        if key not in raw_values:
            return None
        if key in stack:
            chain = " -> ".join([*stack, key])
            raise RuntimeError(f"Circular variable reference in .env: {chain}")
        value, expand = raw_values[key]
        if expand:
            next_stack = {*stack, key}

            def substitute(match: re.Match[str]) -> str:
                variable = match.group(1) or match.group(4)
                operator = match.group(2)
                default = match.group(3) or ""
                replacement = resolve(variable, next_stack)
                if replacement is None or (operator == ":-" and not replacement) or (
                    operator == "-" and replacement is None
                ):
                    if operator in {":-", "-"}:
                        return default
                    raise RuntimeError(
                        f"Variable {key} in .env references an undefined variable: {variable}"
                    )
                return replacement

            value = variable_pattern.sub(substitute, value)
        resolved[key] = value
        return value

    # Resolve after parsing the whole file so references work regardless of order.
    for key in raw_values:
        if key not in os.environ:
            value = resolve(key, set())
            if value is not None:
                os.environ[key] = value


class MarmotAPI:
    def __init__(self, host: str, api_key: str, *, dry_run: bool = False) -> None:
        self.base_url = host.rstrip("/") + API_PREFIX
        self.dry_run = dry_run
        self.http = httpx.Client(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": f"bakery-metadata-enrichment/{ENRICHMENT_VERSION}",
            },
        )
        self.writes = 0

    def close(self) -> None:
        self.http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        optional_404: bool = False,
    ) -> Any:
        if method.upper() not in {"GET", "HEAD"}:
            self.writes += 1
            if self.dry_run:
                print(f"[DRY-RUN] {method.upper()} {path}")
                return None
        response = self.http.request(
            method,
            self.base_url + path,
            params=params,
            json=payload,
        )
        if optional_404 and response.status_code == 404:
            return None
        if not response.is_success:
            detail = response.text.strip().replace("\n", " ")[:600]
            raise RuntimeError(
                f"Marmot API HTTP {response.status_code} {method.upper()} {path}: {detail}"
            )
        if not response.content:
            return None
        try:
            return response.json()
        except json.JSONDecodeError:
            return response.text

    def paginated(self, path: str, list_key: str, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        offset = 0
        # 20 is accepted by all of the list endpoints used here, including
        # glossary and data products, which cap their page size at 20.
        limit = 20
        while True:
            query = dict(params or {})
            query.update({"limit": limit, "offset": offset})
            page = self.request("GET", path, params=query) or {}
            items = page.get(list_key, []) if isinstance(page, dict) else []
            if not isinstance(items, list):
                raise RuntimeError(f"API response is missing the {list_key} list: {path}")
            results.extend(item for item in items if isinstance(item, dict))
            if len(items) < limit:
                break
            offset += len(items)
        return results


def upsert_glossary(api: MarmotAPI) -> dict[str, dict[str, Any]]:
    existing = api.paginated("/glossary/list", "terms")
    by_name = {str(term.get("name", "")).casefold(): term for term in existing}
    root_ids: dict[str, str] = {}
    term_ids: dict[str, str] = {}

    for name, spec in TERMS.items():
        parent_name = spec.get("parent")
        payload: dict[str, Any] = {
            "name": name,
            "definition": spec["definition"],
            "description": spec["description"],
            "metadata": {
                **spec.get("metadata", {}),
                "business_domain": spec["domain"],
                "metadata_language": "en",
                "enrichment_source": METADATA_MARKER,
            },
        }
        if parent_name:
            parent = by_name.get(parent_name.casefold())
            parent_id = root_ids.get(parent_name) or (parent or {}).get("id")
            if parent_id:
                payload["parent_term_id"] = parent_id

        old = by_name.get(name.casefold())
        if old:
            old_id = str(old.get("id", ""))
            old_meta = old.get("metadata") if isinstance(old.get("metadata"), dict) else {}
            # Reuse existing business terms, but update terms previously managed here.
            if old_meta.get("enrichment_source") == METADATA_MARKER:
                term = api.request("PUT", f"/glossary/{quote(old_id, safe='')}", payload=payload) or old
            else:
                term = old
        else:
            term = api.request("POST", "/glossary/", payload=payload) or {}

        term_id = str(term.get("id") or (old or {}).get("id") or "")
        if not term_id and not api.dry_run:
            raise RuntimeError(f"Could not retrieve the glossary term ID for {name!r}")
        term_ids[name] = term_id
        if name == "Bakery Operations":
            root_ids[name] = term_id
        by_name[name.casefold()] = {**(old or {}), **(term or {}), "id": term_id, "name": name}
        print(f"Glossary: {name} {'(existing)' if old else '(created)'}")

    return {name: {"id": term_ids[name], **spec} for name, spec in TERMS.items()}


def find_bakery_assets(api: MarmotAPI) -> dict[str, dict[str, Any]]:
    # Marmot's search filters are case-sensitive. Synced assets use type
    # "Table" and provider "PostgreSQL", so filter locally instead of sending
    # values that can silently produce an empty result.
    # Search once with a large page because Marmot's search ordering can be
    # unstable between pages while ingestion/dbt assets are being indexed.
    # The paginated 20-item traversal can otherwise miss the physical asset
    # for a table that also has a same-named dbt asset.
    search_page = api.request("GET", "/assets/search", params={"limit": 1000, "offset": 0}) or {}
    assets = search_page.get("assets", []) if isinstance(search_page, dict) else []
    found: dict[str, dict[str, Any]] = {}
    expected = set(ASSETS)
    for asset in assets:
        if str(asset.get("type", "")).casefold() != "table":
            continue
        providers = asset.get("providers") or []
        provider_names = {str(provider).casefold() for provider in providers}
        # There can be two same-named assets: the physical PostgreSQL asset
        # and a dbt source/model asset whose provider is simply ``Postgres``.
        # Operational enrichment must target the connector asset so it can
        # preserve and document the complete physical column schema.
        if "postgresql" not in provider_names:
            continue
        name = str(asset.get("name", ""))
        meta = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
        raw_schema = meta.get("schema")
        source_schema = raw_schema.casefold() if isinstance(raw_schema, str) else ""
        if name not in expected:
            continue
        # Require the PostgreSQL plugin's schema metadata. Name-only matching
        # could enrich a same-named table from a different schema.
        if source_schema != "bakery":
            continue
        found[name] = asset

    missing = sorted(expected - found.keys())
    if missing:
        raise RuntimeError(
            f"Not all {len(ASSETS)} operational tables in the bakery schema were found in Marmot. Check that the "
            "PostgreSQL pipeline has synchronized metadata with schema='bakery'; missing tables: "
            + ", ".join(missing)
        )
    return found


def describe_column(table_name: str, column: dict[str, Any]) -> str:
    """Document business meaning and the SQL contract, including controlled values."""
    name = str(column.get("column_name") or column.get("name") or "").strip()
    contract = schema_contracts()[table_name]
    if name not in contract["columns"]:
        raise RuntimeError(f"No project SQL contract for {table_name}.{name}; refresh the schema definitions before enriching.")
    field = contract["columns"][name]
    spec = ASSETS[table_name]
    primary_key = field["primary_key_columns"]
    if name in COLUMN_DETAILS.get(table_name, {}):
        description = COLUMN_DETAILS[table_name][name]
    elif len(primary_key) == 1:
        description = f"Internal primary key uniquely identifying a {spec['title'].lower()} record. Grain: {spec['grain']}"
    elif name in COLUMN_REFERENCE_LABELS:
        description = f"Identifier of the {COLUMN_REFERENCE_LABELS[name]} associated with this {spec['title'].lower()} record"
    elif name in COLUMN_SEMANTICS:
        description = COLUMN_SEMANTICS[name]
    elif field.get("references"):
        target = field["references"]["table"]
        description = f"Identifier of the associated {ASSETS[target]['title'].lower()} record"
    else:
        raise RuntimeError(f"Missing business meaning for {table_name}.{name}.")

    parts = [description.rstrip(".") + "."]
    currency_context = COLUMN_CURRENCY_CONTEXT.get((table_name, name))
    if currency_context:
        parts.append(f"Monetary unit: {currency_context}.")
    allowed = field.get("allowed_values")
    if allowed:
        meanings = ENUM_MEANINGS[(table_name, name)]
        parts.append("Allowed values (SQL CHECK): " + "; ".join(f"{value} = {meanings[value]}" for value in allowed) + ".")
    elif field["sql_type"] == "BOOLEAN":
        parts.append("Allowed boolean values: true and false.")

    nullable = column.get("is_nullable", field["nullable"])
    parts.append("NULL is permitted; absence is not equivalent to a recorded zero/false value." if nullable else "Required: NULL is not permitted.")
    default = column.get("column_default", field["default"])
    if default is not None:
        parts.append(f"SQL default when omitted: {default}.")
    elif not field["identity"]:
        parts.append("No SQL default is declared.")
    if field["identity"]:
        parts.append("Generated by default as an identity; explicit IDs may also be supplied.")
    if primary_key:
        parts.append("Primary key: " + ", ".join(primary_key) + ("; the combination is unique, not each field independently." if len(primary_key) > 1 else "; unique and non-NULL."))
    for keys in field["unique_groups"]:
        parts.append("UNIQUE: " + ", ".join(keys) + "; PostgreSQL permits multiple combinations containing NULL unless otherwise constrained.")
    if reference := field.get("references"):
        parts.append(f"Foreign key: bakery.{reference['table']}.{reference['target_column']}; ON DELETE {reference['on_delete']}.")
    if field["related_checks"]:
        parts.append("Declared CHECK constraints: " + "; ".join(field["related_checks"]) + ".")
    parts.append(f"Declared storage type: {field['sql_type']}.")
    if field["sql_type"].startswith(("VARCHAR(", "CHAR(")):
        length = re.search(r"\d+", field["sql_type"])[0]
        parts.append(f"Maximum character length: {length}.")
    elif field["sql_type"].startswith("NUMERIC("):
        precision, scale = re.findall(r"\d+", field["sql_type"])
        parts.append(f"Decimal precision: {precision} digits; scale: {scale} fractional digits.")
    elif field["sql_type"] == "TIMESTAMPTZ":
        parts.append("Time basis: an absolute instant; use the branch timezone for local business-date reporting.")
    elif field["sql_type"] == "DATE":
        parts.append("Time basis: calendar date without a time-of-day or time-zone component.")
    return " ".join(parts)


def schema_columns(asset: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Decode Marmot's schema map, where `columns` is JSON encoded as a string."""
    raw_schema = asset.get("schema")
    schema = dict(raw_schema) if isinstance(raw_schema, dict) else {}
    raw_columns = schema.get("columns", [])
    if isinstance(raw_columns, str):
        try:
            columns = json.loads(raw_columns)
        except json.JSONDecodeError:
            columns = []
    else:
        columns = raw_columns
    if not isinstance(columns, list):
        columns = []
    return schema, [dict(column) for column in columns if isinstance(column, dict)]


def english_schema(table_name: str, asset: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Enrich the native SQL column schema, preserving other real schema sections."""
    schema, columns = schema_columns(asset)
    for key in LEGACY_SCHEMA_METADATA_KEYS:
        schema.pop(key, None)
    if not columns:
        raise RuntimeError(f"No column schema found in Marmot for {table_name}; sync PostgreSQL schema before enrichment.")
    contract = schema_contracts()[table_name]
    for column in columns:
        name = str(column.get("column_name") or column.get("name") or "")
        field = contract["columns"].get(name)
        if field is None:
            raise RuntimeError(f"Unknown column {table_name}.{name}; update the project schema contract.")
        column.setdefault("is_nullable", field["nullable"])
        column.setdefault("is_primary_key", bool(field["primary_key_columns"]))
        column["is_foreign_key"] = bool(field.get("references"))
        column["declared_sql_type"] = field["sql_type"]
        column["primary_key_columns"] = field["primary_key_columns"]
        column["unique_groups"] = field["unique_groups"]
        column["check_constraints"] = field["related_checks"]
        column["sql_default"] = column.get("column_default", field["default"])
        if reference := field.get("references"):
            column["references"] = reference
        if allowed := field.get("allowed_values"):
            column["allowed_values"] = allowed
            column["value_meanings"] = ENUM_MEANINGS[(table_name, name)]
        elif field["sql_type"] == "BOOLEAN":
            column["allowed_values"] = [True, False]
        if name in ("_created_at", "_last_updated_at", "_is_deleted", "_deleted_at"):
            column["column_role"] = "record_lifecycle_audit"
            column["trigger_managed"] = name != "_is_deleted"
            if name == "_is_deleted":
                column["value_meanings"] = {"false": "Retained for normal operations", "true": "Logically deleted"}
        column["contains_personal_data"] = table_name in ("customers", "employees") and name in ("full_name", "phone", "email", "date_of_birth")
        if unit := COLUMN_CURRENCY_CONTEXT.get((table_name, name)):
            column["monetary_unit"] = unit
        elif (table_name, name) == ("promotions", "discount_value"):
            column["unit_by_promotion_type"] = {"PERCENT": "percent (10 = 10%)", "FIXED_AMOUNT": "VND", "BUNDLE": "undefined by current writer", "LOYALTY_REDEMPTION": "undefined by current offer writer"}
        column["description"] = describe_column(table_name, column)
        # These two keys are the native SQL schema parser's identification
        # contract, including for connectors that use name/type aliases.
        column["column_name"] = name
        column.setdefault("data_type", str(column.get("type") or field["sql_type"]))
    if columns:
        missing = contract["columns"].keys() - {str(c.get("column_name") or c.get("name") or "") for c in columns}
        if missing:
            raise RuntimeError(f"Incomplete Marmot column list for {table_name}: {sorted(missing)}. Sync source schema first.")
        schema["columns"] = json.dumps(columns, ensure_ascii=False, separators=(",", ":"))
    return schema, columns


def business_asset_metadata(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "business_domain": spec["domain"], "business_process": spec["process"],
        "business_grain": spec["grain"], "business_rules": TABLE_RULES[name],
        "data_sensitivity": spec["sensitivity"], "contains_personal_data": spec["sensitivity"] == "personal",
        "metadata_language": "en", "definition_source": schema_contracts()[name]["source"],
        "schema_description": spec["description"],
        "declared_constraints": {key: schema_contracts()[name][key] for key in ("primary_key", "unique", "checks", "foreign_keys")},
        "record_lifecycle": ROW_AUDIT_POLICY,
        "default_row_filter": "_is_deleted = false",
        "application_rule_source": "generate_script/simulate_operations.py",
        "foreign_keys": schema_contracts()[name]["foreign_keys"],
        "referenced_by": [
            {"schema": "bakery", "table": child, "column": reference["column"], "target_column": reference["target_column"], "on_delete": reference["on_delete"]}
            for child, contract in schema_contracts().items()
            for reference in contract["foreign_keys"]
            if reference["table"] == name
        ],
        "constraint_scope": "Declared constraints from project SQL; application calculations are described separately and are not SQL-enforced identities.",
        METADATA_MARKER: ENRICHMENT_VERSION,
    }


def render_ui_page_content(table_name: str, spec: dict[str, Any], columns: list[dict[str, Any]]) -> str:
    """Render HTML accepted by Marmot's rich-text Pages editor."""
    esc = html.escape
    parts = [
        f"<h2>{esc(spec['title'])}</h2>",
        f"<p>{esc(spec['description'])}</p>",
        "<h3>Grain</h3>",
        f"<p>{esc(spec['grain'])}</p>",
        "<h3>Business process</h3>",
        f"<p>{esc(spec['process'])}</p>",
        "<h3>Data relationships</h3>",
        f"<p>{esc(spec['relationships'])}</p>",
        "<h3>Business rules and calculation guidance</h3>",
        "<ul>" + "".join(f"<li>{esc(rule)}</li>" for rule in TABLE_RULES[table_name]) + "</ul>",
        "<p>Application behavior is documented separately from SQL constraints; an intended reconciliation or workflow is not automatically enforced by the database.</p>",
        "<h3>Record lifecycle and soft deletion</h3>",
        "<ul>" + "".join(f"<li><strong>{esc(key)}</strong>: {esc(value)}</li>" for key, value in ROW_AUDIT_POLICY.items()) + "</ul>",
        "<h3>Declared database constraints</h3>",
        "<ul>",
    ]
    contract = schema_contracts()[table_name]
    parts.append(f"<li>PRIMARY KEY: <code>{esc(', '.join(contract['primary_key']))}</code></li>")
    for keys in contract["unique"]:
        parts.append(f"<li>UNIQUE: <code>{esc(', '.join(keys))}</code>; NULL-containing combinations remain distinct.</li>")
    for expression in contract["checks"]:
        parts.append(f"<li>CHECK: <code>{esc(expression)}</code></li>")
    for reference in contract["foreign_keys"]:
        target = f"bakery.{reference['table']}.{reference['target_column']}"
        parts.append(f"<li>FOREIGN KEY: <code>{esc(reference['column'])}</code> → <code>{esc(target)}</code>; ON DELETE {esc(reference['on_delete'])}.</li>")
    parts.extend([
        "</ul>",
        "<h3>Schema Content</h3>",
        "<p>Column meanings, value domains, units, NULL/default behavior, keys and declared storage constraints.</p>",
    ])
    if columns:
        parts.append("<ul>")
        for column in columns:
            column_name = str(column.get("column_name") or column.get("name") or "")
            data_type = str(column.get("data_type") or column.get("type") or "")
            nullable = "Nullable" if column.get("is_nullable") else "NOT NULL"
            key_flags = []
            if column.get("is_primary_key"):
                key_flags.append("PK")
            if column.get("is_foreign_key"):
                key_flags.append("FK")
            key_text = f"; {', '.join(key_flags)}" if key_flags else ""
            description = describe_column(table_name, column)
            parts.append(
                "<li><strong>"
                + esc(column_name)
                + "</strong> (<code>"
                + esc(data_type)
                + "</code>; "
                + esc(nullable + key_text)
                + "): "
                + esc(description)
                + "</li>"
            )
        parts.append("</ul>")
    else:
        parts.append("<p>The catalog has not supplied the column list.</p>")
    if spec["note"]:
        parts.extend(["<h3>Usage notes</h3>", f"<p>{esc(spec['note'])}</p>"])
    terms = spec.get("terms", ())
    if terms:
        parts.extend(["<h3>Glossary</h3>", f"<p>{esc(', '.join(terms))}</p>"])
    parts.append(f"<p><em>Constraint source: {esc(contract['source'])}. Column shape: synchronized PostgreSQL catalog. Application rules: generate_script/simulate_operations.py.</em></p>")
    return "\n".join(parts)


def flatten_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for page in pages:
        flattened.append(page)
        children = page.get("children")
        if isinstance(children, list):
            flattened.extend(flatten_pages([child for child in children if isinstance(child, dict)]))
    return flattened


def remove_generator_metadata(api: MarmotAPI) -> None:
    """Remove the legacy generator log asset, its pages and its glossary term."""
    action = "would remove" if api.dry_run else "removed"
    for asset in api.paginated("/assets/search", "assets"):
        metadata = asset.get("metadata") or {}
        providers = {str(provider).casefold() for provider in asset.get("providers", [])}
        if (
            asset.get("name") != "simulation_runs"
            or str(asset.get("type", "")).casefold() != "table"
            or metadata.get("schema") != "bakery"
            or not any("postgres" in provider for provider in providers)
        ):
            continue
        asset_id = str(asset["id"])
        mrn = str(asset["mrn"])
        page_tree = api.request("GET", f"/docs/entity/asset/{quote(mrn, safe='')}/pages") or {}
        # Delete children before parents, then delete the asset. Marmot also
        # removes its membership links; the source PostgreSQL table is untouched.
        for page in reversed(flatten_pages(page_tree.get("pages", []))):
            api.request("DELETE", f"/docs/pages/{quote(str(page['id']), safe='')}")
        api.request("DELETE", f"/assets/{quote(asset_id, safe='')}")
        print(f"Generator metadata: {action} bakery.simulation_runs from Marmot")

    for term in api.paginated("/glossary/list", "terms"):
        if term.get("name") == "Bakery: Simulation Run":
            api.request("DELETE", f"/glossary/{quote(str(term['id']), safe='')}")
            print(f"Generator metadata: {action} the Simulation Run glossary term")


def upsert_ui_documentation_page(
    api: MarmotAPI,
    mrn: str,
    table_name: str,
    spec: dict[str, Any],
    columns: list[dict[str, Any]],
) -> None:
    """Create/update a root Page shown in the asset's UI Documentation tab."""
    page_title = f"Bakery — {table_name}"
    entity_path = f"/docs/entity/asset/{quote(mrn, safe='')}/pages"
    page_tree = api.request("GET", entity_path) or {}
    root_pages = page_tree.get("pages", []) if isinstance(page_tree, dict) else []
    all_pages = flatten_pages([page for page in root_pages if isinstance(page, dict)])
    page = next((item for item in all_pages if item.get("title") == page_title), None)
    content = render_ui_page_content(table_name, spec, columns)
    if page and page.get("id"):
        api.request(
            "PUT",
            f"/docs/pages/{quote(str(page['id']), safe='')}",
            payload={"title": page_title, "content": content},
        )
        print(f"UI Page: {table_name} (updated)")
    else:
        api.request("POST", entity_path, payload={"title": page_title, "content": content})
        print(f"UI Page: {table_name} (created)")


def enrich_assets(
    api: MarmotAPI,
    assets: dict[str, dict[str, Any]],
    glossary: dict[str, dict[str, Any]],
) -> None:
    for name, spec in ASSETS.items():
        asset = assets[name]
        asset_id = str(asset.get("id", ""))
        mrn = str(asset.get("mrn", ""))
        if not asset_id or not mrn:
            raise RuntimeError(f"Asset {name!r} is missing its ID or MRN in the Marmot API.")

        # Search results can omit column schema; fetch the complete asset before
        # writing so Schema Content and connector metadata are preserved.
        full_asset = api.request("GET", f"/assets/{quote(asset_id, safe='')}") or asset
        metadata = full_asset.get("metadata") if isinstance(full_asset.get("metadata"), dict) else {}
        merged_metadata = dict(metadata)
        merged_metadata.update(
            business_asset_metadata(name, spec)
        )
        current_tags = full_asset.get("tags") if isinstance(full_asset.get("tags"), list) else []
        tags = sorted({str(tag) for tag in current_tags} | {"bakery", *spec["tags"]})
        schema, columns = english_schema(name, full_asset)
        payload: dict[str, Any] = {"metadata": merged_metadata, "tags": tags}
        if schema:
            payload["schema"] = schema

        # These bakery definitions are maintained by this script. Update both
        # fields even when the catalog still contains earlier Vietnamese text.
        payload["description"] = spec["description"]
        payload["user_description"] = spec["description"]

        api.request("PUT", f"/assets/{quote(asset_id, safe='')}", payload=payload)

        upsert_ui_documentation_page(api, mrn, name, spec, columns)

        term_ids = [glossary[term]["id"] for term in spec["terms"] if glossary.get(term, {}).get("id")]
        if term_ids:
            existing_terms = api.request("GET", f"/assets/terms/{quote(asset_id, safe='')}") or []
            existing_ids = {
                str(term.get("term_id"))
                for term in existing_terms
                if isinstance(term, dict) and term.get("term_id")
            }
            additions = [term_id for term_id in term_ids if term_id not in existing_ids]
            if additions:
                api.request(
                    "POST",
                    f"/assets/terms/{quote(asset_id, safe='')}",
                    payload={"term_ids": additions},
                )
        print(f"Asset: {name}")


def upsert_data_products(api: MarmotAPI, assets: dict[str, dict[str, Any]]) -> None:
    existing = api.paginated("/products/list", "data_products")
    by_name = {str(product.get("name", "")).casefold(): product for product in existing}

    for name, spec in PRODUCTS.items():
        missing_asset_names = sorted(set(spec["tables"]) - assets.keys())
        if missing_asset_names:
            raise RuntimeError(f"Data product {name} references missing tables: {missing_asset_names}")

        payload = {
            "name": name,
            "description": spec["description"],
            "metadata": {**spec["metadata"], "metadata_language": "en"},
            "tags": sorted(set(spec["tags"]) | {"bakery"}),
        }
        old = by_name.get(name.casefold())
        if old:
            product_id = str(old.get("id", ""))
            if not product_id:
                raise RuntimeError(f"Data product {name!r} already exists but has no ID.")
            old_meta = old.get("metadata") if isinstance(old.get("metadata"), dict) else {}
            merged_meta = dict(old_meta)
            merged_meta.update(payload["metadata"])
            old_tags = old.get("tags") if isinstance(old.get("tags"), list) else []
            payload["metadata"] = merged_meta
            payload["tags"] = sorted({str(tag) for tag in old_tags} | set(payload["tags"]))
            api.request("PUT", f"/products/{quote(product_id, safe='')}", payload=payload)
            print(f"Data product: {name} (updated)")
        else:
            created = api.request("POST", "/products/", payload=payload) or {}
            product_id = str(created.get("id", ""))
            if not product_id and not api.dry_run:
                raise RuntimeError(f"Could not retrieve the ID after creating data product {name!r}.")
            print(f"Data product: {name} (created)")

        if api.dry_run or not product_id:
            continue
        current_ids: set[str] = set()
        offset = 0
        limit = 20
        while True:
            current = api.request(
                "GET",
                f"/products/assets/{quote(product_id, safe='')}",
                params={"limit": limit, "offset": offset},
            ) or {}
            page_ids = [str(asset_id) for asset_id in current.get("asset_ids", [])]
            current_ids.update(page_ids)
            if len(page_ids) < limit:
                break
            offset += len(page_ids)
        desired_ids = {str(assets[table_name]["id"]) for table_name in spec["tables"]}
        additions = sorted(desired_ids - current_ids)
        if additions:
            api.request(
                "POST",
                f"/products/assets/{quote(product_id, safe='')}",
                payload={"asset_ids": additions},
            )
        print(f"  Assets: {len(desired_ids)} tables, {len(additions)} new memberships")


def enrich_glossary_synonyms_and_tags(
    api: MarmotAPI,
    assets: dict[str, dict[str, Any]],
) -> None:
    """Use Marmot's ingestion batch endpoint for glossary synonyms and tags.

    The glossary CRUD endpoints do not expose synonyms/tags. The batch endpoint
    does, and it requires a non-empty asset list, so this records a real,
    separately named metadata-enrichment run containing the already-enriched
    bakery assets plus their current fields.
    """
    if api.dry_run:
        run_id = str(uuid4())
    else:
        started = api.request(
            "POST",
            "/runs/start",
            payload={
                "pipeline_name": ENRICHMENT_PIPELINE,
                "source_name": ENRICHMENT_SOURCE,
                "config": {"purpose": "Glossary synonyms and tags for the Bakery catalog"},
            },
        ) or {}
        run_id = str(started.get("run_id", ""))
        if not run_id:
            raise RuntimeError("Marmot did not return a run_id when starting the metadata enrichment run.")

    batch_assets: list[dict[str, Any]] = []
    for table_name, asset_ref in assets.items():
        asset_id = str(asset_ref.get("id", ""))
        current = api.request("GET", f"/assets/{quote(asset_id, safe='')}") or asset_ref
        metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
        spec = ASSETS[table_name]
        merged_metadata = dict(metadata)
        merged_metadata.update(
            business_asset_metadata(table_name, spec)
        )
        current_terms = current.get("terms") if isinstance(current.get("terms"), list) else []
        term_names = {str(term) for term in current_terms}
        term_names.update(spec["terms"])
        current_tags = current.get("tags") if isinstance(current.get("tags"), list) else []
        schema, _ = english_schema(table_name, current)
        batch_asset = {
            "name": current.get("name", table_name),
            "type": current.get("type", "Table"),
            "providers": current.get("providers", ["postgresql"]),
            "description": spec["description"],
            "external_links": current.get("external_links", []),
            "metadata": merged_metadata,
            "schema": schema,
            "sources": current.get("sources", []),
            "tags": sorted({str(tag) for tag in current_tags} | {"bakery", *spec["tags"]}),
            "terms": sorted(term_names),
        }
        batch_assets.append(batch_asset)

    glossary_terms = []
    for name, spec in TERMS.items():
        glossary_terms.append(
            {
                "name": name,
                "definition": spec["definition"],
                "description": spec["description"],
                "parent": spec.get("parent", ""),
                "synonyms": list(GLOSSARY_SYNONYMS.get(name, ())),
                "tags": sorted({"bakery", "business-glossary", spec["domain"]}),
                "metadata": {
                    **spec.get("metadata", {}),
                    "business_domain": spec["domain"],
                    "metadata_language": "en",
                    "enrichment_source": METADATA_MARKER,
                },
            }
        )

    try:
        api.request(
            "POST",
            "/runs/assets/batch",
            payload={
                "pipeline_name": ENRICHMENT_PIPELINE,
                "source_name": ENRICHMENT_SOURCE,
                "run_id": run_id,
                "assets": batch_assets,
                "glossary_terms": glossary_terms,
            },
        )
        api.request(
            "POST",
            "/runs/complete",
            payload={
                "run_id": run_id,
                "status": "completed",
                "summary": {
                    "assets_created": 0,
                    "assets_updated": len(batch_assets),
                    "assets_deleted": 0,
                    "assets_terms_linked": 0,
                    "documentation_added": 0,
                    "glossary_terms_created": 0,
                    "glossary_terms_updated": len(glossary_terms),
                    "lineage_created": 0,
                    "lineage_updated": 0,
                    "total_entities": len(batch_assets) + len(glossary_terms),
                    "errors_count": 0,
                    "duration_seconds": 0,
                },
            },
        )
    except Exception:
        if not api.dry_run:
            try:
                api.request(
                    "POST",
                    "/runs/complete",
                    payload={"run_id": run_id, "status": "failed", "error": "Metadata enrichment batch failed."},
                )
            except Exception:
                pass
        raise

    # The batch request model does not expose these asset fields. Restore them
    # through the regular asset update API after the batch upsert.
    for table_name, asset_ref in assets.items():
        asset_id = str(asset_ref.get("id", ""))
        restore: dict[str, Any] = {
            "user_description": ASSETS[table_name]["description"],
        }
        if "environments" in asset_ref:
            restore["environments"] = asset_ref["environments"]
        api.request("PUT", f"/assets/{quote(asset_id, safe='')}", payload=restore)
    print(f"Glossary synonyms/tags: updated {len(glossary_terms)} terms through run {ENRICHMENT_PIPELINE}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check connectivity and the update plan without writing changes to Marmot.",
    )
    args = parser.parse_args()

    try:
        validate_details(set(ASSETS))
        for name, contract in schema_contracts().items():
            for column_name in contract["columns"]:
                describe_column(name, {"column_name": column_name})
            unknown_terms = set(ASSETS[name]["terms"]) - TERMS.keys()
            if unknown_terms:
                raise RuntimeError(f"Unknown glossary links on {name}: {sorted(unknown_terms)}")
        load_env_file(ENV_FILE)
        host = os.environ.get("MARMOT_HOST", "").strip()
        api_key = os.environ.get("MARMOT_API_KEY", "").strip()
        if not host or not api_key:
            raise RuntimeError(".env must define MARMOT_HOST and MARMOT_API_KEY.")

        api = MarmotAPI(host, api_key, dry_run=args.dry_run)
        try:
            print(f"Reading the catalog from {host.rstrip('/')}")
            assets = find_bakery_assets(api)
            print(f"Found all {len(assets)} bakery tables.")
            # Validate all source/cached shapes before the first mutation so
            # stale or incomplete connector schemas cannot yield a half-audit.
            column_count = 0
            for name, asset in assets.items():
                full = api.request("GET", f"/assets/{quote(str(asset['id']), safe='')}") or asset
                _, columns = english_schema(name, full)
                column_count += len(columns)
                assets[name] = full
            print(f"Validated business definitions and SQL contracts for {column_count} columns before writing.")
            remove_generator_metadata(api)
            glossary = upsert_glossary(api)
            enrich_assets(api, assets, glossary)
            enrich_glossary_synonyms_and_tags(api, assets)
            upsert_data_products(api, assets)
            if args.dry_run:
                print(f"Dry-run complete; {api.writes} write requests planned, no changes submitted.")
            else:
                print("Completed metadata enrichment for assets, glossary, and data products.")
        finally:
            api.close()
        return 0
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        print(f"Metadata enrichment failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
