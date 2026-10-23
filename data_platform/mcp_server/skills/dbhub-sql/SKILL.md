---
name: dbhub-sql
description: Prefer curated DBHub tools for management reports; use read-only Cube SQL for analyses outside their scope.
---

# DBHub over Cube SQL API

DBHub is connected to **Cube's SQL API**, which speaks the PostgreSQL wire
protocol. It is not connected directly to the operational PostgreSQL database.
SQL therefore sees Cube's exposed semantic model and is limited to the SQL
features that this Cube deployment supports. Do not assume every PostgreSQL
function, source table or source schema is available.

## Management reports: named tools first

This assistant serves managers and stakeholders. DBHub exposes curated reporting
tools whose SQL is already written and parameterized in `data_platform/dbhub/dbhub.toml`.
For a covered question, call the named tool directly with values; do not write SQL
or inspect Cube schemas just to reproduce that report. Use Marmot to establish
business meaning as needed; reuse sufficient context already retrieved.

| Stakeholder question | Tool |
| --- | --- |
| What dates are available? Is today's report complete? | `get_reporting_coverage` (coverage only, not proof of pipeline success) |
| Revenue, orders, discounts, refunds, average ticket? | `get_sales_summary` |
| How did this period compare with the previous one? | `get_sales_comparison` |
| What is the daily sales trend? | `get_sales_trend` |
| Which branches perform best? | `get_branch_performance` |
| Which sales channels contribute revenue? | `get_channel_performance` |
| Which products sell best by net line revenue? | `get_product_performance` |
| How many identified customers bought repeatedly within this period? | `get_customer_purchase_segments` |
| What is our current stock by branch/item/unit? | `get_inventory_position` |
| Which lots are expired or expiring soon? | `get_inventory_expiry` |
| What output did production achieve, and how much waste was recorded? | `get_production_waste_summary` |
| Which purchase-order lines remain outstanding or overdue? | `get_procurement_backlog` |
| Which closed shifts have cash shortages or surpluses? | `get_cash_variances` |

The named tools appear at runtime through the same DBHub MCP connection. If a
tool is absent, disclose that limitation; do not claim it ran. Inputs contain
dates, branch codes, horizons and limits, never SQL. Optional `branch_code=""`
means all branches. Resolve branch names using `get_branch_performance` when
needed; never invent a branch code. All business-date start/end ranges are
inclusive and use Asia/Ho_Chi_Minh. Reject reversed date ranges before calling.
For procurement, reference_date is an end-of-local-day cutoff. Do not label
deliveries later today as already overdue; use yesterday for overdue as of
the start of today, or a precise timestamp SQL query for overdue right now.

For current/latest reports, consult coverage and explicitly state any gap
between the requested dates and available data. Do not change the requested
period silently or treat missing days as confirmed zeros. `latest_source_change_at`
is a source-change watermark, not the last successful refresh time. Longer
trend requests must be split into <=1000-day windows. Reaching any documented
row limit means completeness has not been established; disclose or narrow the
scope instead of computing full totals from a top-N/exception list.

Sales summary/comparison/branch/channel/customer tools separate currencies.
Trend and product marts lack a currency column: confirm single-currency VND
scope with `get_sales_summary` before using their financial totals. Otherwise
query currency-separated facts. Refunds in these sales tools are attributed
to the original sale date, not the return event date. Receipt revenue includes
tax and receipt-level adjustments; product-line sales do not. Average ticket
is total receipt revenue / total orders, not an average of daily averages.
After-refund revenue is not profit: these tools do not establish COGS, payroll,
rent or a complete P&L. Calculate growth only with a nonmissing, nonzero baseline;
keep the two periods and any unequal coverage explicit.

Inventory is the latest materialized stock snapshot. A reference date on the
expiry tool only classifies those existing lots; it cannot reconstruct past
stock. Lots expiring on the reference date are not yet expired under the mart
date rule. Keep units/item identities separate and do not infer inventory
valuation, reorder alerts or days of cover from tools that do not return them.
Usable stock is classified at snapshot date; stale snapshot dates must be
disclosed. Procurement uses current fulfillment even for a past reference date;
unit-mismatch lines do not prove a shortage. Waste spans stock items and is not
a comparable numerator for production yield or a waste-rate denominator.
Customer repeat segments are within-window repeat purchases, not lifetime
retention or new-vs-returning classification. Anonymous order count does not
establish a unique customer count.

## Ad hoc queries

Use DBHub's `execute_sql` when a question needs a CTE, subquery, window calculation or another
SQL composition that is awkward or unavailable in Cube's structured REST
query and no named report covers it. A simple grouped measure query outside the reports is usually clearer through
`run_cube_query`. Marmot remains the source for business definitions and
ownership; `inspect_cube_model` remains the source for available REST members.

## `search_objects`

Explore the Cube SQL schema before writing SQL when table or column names are
unknown. Input uses SQL LIKE patterns. Start with names; request `full` detail
only for the relevant objects. The current Cube SQL catalog exposes modeled
tables under `public`.

```json
{"object_type": "table", "schema": "public", "pattern": "sale%", "detail_level": "names"}
```

```json
{"object_type": "column", "schema": "public", "table": "sales", "detail_level": "full"}
```

If this optional tool is not present or the Cube SQL catalog cannot answer a
schema search, use `inspect_cube_model` and a bounded SQL query to inspect the
available model. Do not infer business meaning from names alone.

## `execute_sql`

Pass SQL in the required `sql` string. This connection is configured read-only;
use SELECT queries. Bound exploratory results with `LIMIT`. Simple CTEs and
subqueries work in this deployment, while more complex SQL is subject to
Cube's SQL planner. The result contains a `success` flag and
statement rows; an MCP tool response can exist even when `success` is false.

```json
{"sql": "WITH counts AS (SELECT COUNT(*) AS n FROM sales) SELECT n FROM counts"}
```

The example illustrates the tool format, not an answer plan. Before combining
tables or aggregates, establish the row grain and join keys from catalog/model
context. Keep receipt-level totals separate from item-level rows when a join
could multiply them. This rule applies generally to fact tables with different
grains. Prefer an explicit time filter and timezone handling when dates matter.
Cube SQL timestamps may be presented in UTC; verify their time basis before
mapping timestamps to a local business day. A local-date filter may require
converted boundaries rather than `CAST(timestamp AS DATE)`.

## Joining Cube models

Cube's SQL API follows joins declared in the semantic model. On this deployment,
a normal SQL join predicate using source key columns is rejected for Cube-to-Cube
joins. Use the virtual `__cubeJoinField` on both sides. This is Cube SQL syntax,
not a physical key column. Join direction and query shape may affect whether
Cube can plan the statement.

```json
{"sql": "SELECT sale_items.product_id, sales.status FROM sale_items JOIN sales ON sale_items.__cubeJoinField = sales.__cubeJoinField LIMIT 3"}
```

The example shows the join syntax and has been checked against this deployment.
For analyses that also need CTEs, first try the modeled join in a base SELECT,
then compose the remaining calculation. Cube may reject joins between CTEs
that individually wrap Cube tables. If the planner reports an unsupported
rewrite, simplify the SQL shape or use model-supported semantic queries while
preserving the requested calculation. Do not report a failed tool response as
data.

References: [DBHub tool configuration](https://github.com/bytebase/dbhub/blob/main/docs/config/toml.mdx),
[DBHub SQL tool](https://github.com/bytebase/dbhub/blob/main/docs/tools/execute-sql.mdx),
[Cube SQL joins](https://docs.cube.dev/reference/core-data-apis/sql-api/joins).
