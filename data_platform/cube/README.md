# Bakery Cube model

The 33 operational cubes read `bakery.<table>` through a source SQL filter
`WHERE NOT _is_deleted`. They expose the four prefixed lifecycle fields as
three time dimensions and one boolean dimension. `simulation_runs` is a
separate simulator cube and has no new lifecycle columns.

`inspect_cube_model` reports this execution model, not business documentation.
DBHub connects to Cube's SQL API and inherits these filters and dimensions;
it requires no new DSN or table-specific settings. Deleted source rows are
intentionally not exposed by the normal Cube/DBHub reporting path, even if a
caller requests `_is_deleted=true`. Use raw operational/staging data for
explicit deletion audits.

The analytics marts are exposed through the same PostgreSQL connector. Cube
now includes `dim_date` and `fct_daily_weather` with every physical column,
plus a count measure; `fct_daily_weather` uses a deterministic composite-row
key because its physical grain is `(weather_date, location_code,
weather_source)`. Cube API and refresh worker use PostgreSQL with
`duckdb.force_execution=true`, so analytical SQL is executed by pg_duckdb
without introducing a separate DuckDB database file.

Cube/query refresh keys and existing rollups use a one-minute refresh cadence;
changes are eventually visible after cache checks/rebuilds, not guaranteed
synchronously at the source commit. Reload/restart `cube_api` and
`cube_refresh_worker` after deployment if development file reload is disabled.
Lifecycle fields are database write times. Use the table's business event time
for historical reporting. Soft deletion does not automatically cascade to
children or reverse inventory, payments, cash or loyalty.
