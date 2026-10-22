---
name: perspective
description: Display verified query results as one interactive Perspective chart, pivot table or Number Card.
---

# Scope

`inspect_perspective` lists installed browser plugins and their column roles. This is
visualization capability information, not Marmot business context or Cube model metadata.

`render_perspective` displays **one visualization per call**: a chart, data grid/pivot or
Number Card. Supply one typed `table` and one native `view` configuration. Dashboard
layouts, tabs, multiple panels and master/detail filtering are not part of this tool.
When multiple visuals are needed, present them separately. Do not generate another UI,
HTML, JavaScript, SQL or ECharts options in visualization arguments.

# Data contract

Query Cube or DBHub before rendering. `table` contains `name`, `schema`, verified `rows`
(up to 2,000) and an optional description. Schema types are `string`, `integer`, `float`,
`boolean`, `date` and `datetime`. Numeric query-result strings are converted using their
declared type; large identifiers should remain strings. Empty tables still require schema.

Describe the period, timezone, units, grain, query filters and truncation in `description`.
Keep incompatible grains separate; summing a header total duplicated across detail rows is
incorrect. Already aggregated averages, percentages and distinct counts are not additive.
Query the correct scalar or suitable components instead of summing them again.

Native filters and pivots operate on these supplied rows, without calling the database
or the agent. Include filter fields at the appropriate grain. A daily total without a
branch field cannot be filtered by branch. Changing the period beyond the supplied data
requires a new query. Prefer aggregate data over personal records when it answers the request.

# View configuration

Use an exact installed `plugin` and its inspected positional `columns` roles. Optional
`group_by`, `split_by`, `aggregates`, `sort` and `filter` use Perspective's native syntax.
All referenced fields must exist in the supplied table. For temporal trends, specify order.

- Sort: `[["Day", "asc"]]`.
- Filters: `[["Region", "==", "West"], ["Amount", ">=", 100]]`.
- An `in` filter uses an array value: `[["Region", "in", ["West", "East"]]]`.
- Aggregates: `{"Amount": "sum"}`. Choose an aggregate appropriate to the source grain.

Do not invent plugin names. The user can change visual type, groups, splits and filters
through native viewer settings. The host also provides reset, fullscreen and JSON export.
Export includes the supplied rows, not only the currently filtered subset.

## Number Card

The project plugin `Number Card` displays exactly one numeric field. Provide one summary
row without `group_by`, or use a grouping field and an explicit aggregate to display the
engine's grand total over multiple rows. No `split_by`. Optional `plugin_config` accepts
`unit` (verified label), `locale` (default `vi-VN`) and `decimals` (maximum decimal places,
default 2). Do not infer a currency. Empty/null scalar results display a dash; observed
zero displays 0. A precomputed summary cannot be refiltered into detail that was not supplied.

# Example

The following is a shape example; use actual verified query rows in a real call.

```json
{
  "title": "Amount by day",
  "description": "Verified daily totals, test units. Filters apply only to the supplied rows.",
  "table": {
    "name": "daily_amount",
    "schema": {"Day": "date", "Amount": "float"},
    "rows": [{"Day": "2026-09-01", "Amount": 120}, {"Day": "2026-09-02", "Amount": 150}]
  },
  "view": {
    "plugin": "Y Line",
    "columns": ["Amount"],
    "group_by": ["Day"],
    "aggregates": {"Amount": "sum"},
    "sort": [["Day", "asc"]]
  }
}
```

# Completion

Rendering returns `ready` only after the native view renders. On `error`, use the returned
validation or initialization details to correct the configuration. Do not claim that a
visualization exists before successful completion, or call a displayed table a dashboard.
