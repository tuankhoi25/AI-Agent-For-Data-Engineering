---
name: cube-semantic
description: Inspect Cube's queryable model and run structured Semantic Query API requests for model-supported analysis.
---

# Cube semantic model and REST queries

Cube exposes modeled measures, dimensions, segments and joins. The two tools
below use Cube's REST API. They do not read Marmot's business catalog and do not
accept SQL. Use business definitions from Marmot when meaning or data grain is
unclear.

For common management reports covered by DBHub's named reporting tools, prefer
those tools and pass their parameters directly. Inspect Cube members and build
a REST query when the question falls outside the named reports' scope; do not
recreate a curated report unnecessarily.

## `inspect_cube_model`

Use without `cube_names` to list the available cubes. Supply a list of exact
cube names to get their measures, dimensions, segments and available types.
This describes what Cube can query; it is not the source database's column
documentation or a query result.

```json
{"cube_names": ["sales", "sale_items"]}
```

## `run_cube_query`

Use a `query` object in Cube's Semantic Query API format. Measures calculate
values; dimensions group or select fields; a time dimension filters a date
range and groups only when `granularity` is supplied. Use exact member names
returned by `inspect_cube_model`. The tool supports `measures`, `dimensions`,
`timeDimensions`, `filters`, `segments`, `order`, `limit`, `offset`, `timezone`
and `ungrouped`. `order` is an object mapping member names to `asc` or `desc`.
Grouping follows the selected dimensions; do not add a SQL-style `groupBy`.

```json
{
  "query": {
    "measures": ["sales.count"],
    "timeDimensions": [{
      "dimension": "sales.completed_at",
      "dateRange": "last 7 days",
      "granularity": "day"
    }],
    "filters": [{
      "member": "sales.status",
      "operator": "equals",
      "values": ["COMPLETED"]
    }],
    "order": {"sales.completed_at.day": "asc"},
    "timezone": "Asia/Ho_Chi_Minh",
    "limit": 100
  }
}
```

The example shows input shape, not a default metric, status or date period.
Choose filters, grain, range and result size from the user's question. An
empty result applies to that specific query. When analysis needs SQL constructs
that the semantic JSON cannot express, use DBHub's Cube SQL connection. Check
tool errors and do not silently change the requested metric to make a query
succeed.

Reference: [Cube query format](https://docs.cube.dev/reference/core-data-apis/rest-api/query-format).
