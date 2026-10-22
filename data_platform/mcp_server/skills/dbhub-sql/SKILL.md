---
name: dbhub-sql
description: Explore Cube's PostgreSQL-compatible SQL surface through DBHub and run read-only SQL when structured Cube queries cannot express the analysis clearly.
---

# DBHub over Cube SQL API

DBHub is connected to **Cube's SQL API**, which speaks the PostgreSQL wire
protocol. It is not connected directly to the operational PostgreSQL database.
SQL therefore sees Cube's exposed semantic model and is limited to the SQL
features that this Cube deployment supports. Do not assume every PostgreSQL
function, source table or source schema is available.

Use DBHub when a question needs a CTE, subquery, window calculation or another
SQL composition that is awkward or unavailable in Cube's structured REST
query. A simple grouped measure query is usually clearer through
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
