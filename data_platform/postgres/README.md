# Bakery PostgreSQL schema and row lifecycle

## Scope

`02_branches.sql` through `34_cash_movements.sql`, plus `36_weather_daily.sql`, define 34 operational
tables, including bridges with composite keys. Every table has:

| Column | Type/default | Ownership and meaning |
|---|---|---|
| `_created_at` | TIMESTAMPTZ NOT NULL, real DB time | Set on INSERT, immutable on UPDATE |
| `_last_updated_at` | TIMESTAMPTZ NOT NULL, real DB time | Updated on every INSERT/UPDATE, including no-op, soft delete and restore |
| `_is_deleted` | BOOLEAN NOT NULL DEFAULT FALSE | Caller changes this flag for logical deletion/restoration |
| `_deleted_at` | TIMESTAMPTZ NULL | Set on entry to deleted state, preserved while deleted, cleared on restore |

`35_simulation_runs.sql` is a generator control table and is excluded. Tool
schemas (`marmot`, `cube_core`) and derived analytics tables are not operational
source tables and are not modified by these initialization scripts.

`01_row_audit.sql` defines `bakery.set_row_audit()`. Each operational table
attaches the same `BEFORE INSERT OR UPDATE FOR EACH ROW` trigger. Defaults
make the shape explicit; the trigger overrides caller-supplied audit timestamps.
`clock_timestamp()` is real database wall-clock time, with row-local monotonic
protection on UPDATE. It is not transaction start time, business event time or
a commit sequence. `_last_updated_at >= _created_at` and the flag/deletion-time
pair are checked by constraints.

The existing unprefixed `created_at` fields on `branches`/`products` are
retained for compatibility. New lifecycle metadata uses the prefixed columns.
These four fields describe the latest row state, not a full change log.

## New databases

The Compose mount `/docker-entrypoint-initdb.d` runs the top-level SQL files
in filename order when the PostgreSQL data directory is empty. The function
is created before any business table, and triggers are attached before seeds.
The `migrations/` directory is not executed recursively by the entrypoint and
is intentionally unused. This personal project recreates the source database
from the numbered initialization scripts instead of maintaining migrations for
existing volumes. If the source schema is incomplete, remove the PostgreSQL
volume and run the normal bootstrap flow again.

## Logical deletion and restoration

```sql
-- Hide a row; trigger sets _deleted_at and updates _last_updated_at.
UPDATE bakery.products SET _is_deleted = TRUE WHERE product_id = 123;

-- Restore it; trigger clears _deleted_at, retaining _created_at.
UPDATE bakery.products SET _is_deleted = FALSE WHERE product_id = 123;

-- Normal source reads must opt into the retained-row policy.
SELECT * FROM bakery.products WHERE NOT _is_deleted;
```

There is no automatic cascading logical deletion and no automatic stock,
payment, cash or loyalty reversal. A real refund/cancellation uses its normal
business workflow, not this metadata flag. Keep linked records consistent in
one transaction when logically removing erroneous data. Existing foreign keys
and unique keys still apply to deleted rows. `DELETE` is not intercepted and
retains its physical-delete/FK behavior; use UPDATE for soft deletion.

## Downstream deployment order

    1. Run the Marmot ingestion pipeline to refresh all operational columns,
   then run `python3 data_platform/marmot/enrich_bakery_metadata.py`. Merely
   registering a schedule does not run ingestion. English definitions cover
   lifecycle fields, triggers, state transitions, units and business meanings.
2. Run `./.venv/bin/python analytics/run_pipeline.py --check` for offline
   validation. After the platform and bakery bootstrap are ready, use
   `./.venv/bin/python analytics/run_pipeline.py --run` for one manual ETL
   batch. This runs `dbt build`, including snapshots and tests. Staging appends
   source versions, core/facts retain tombstones for dependency propagation,
   and reporting marts exclude deleted rows. All snapshots are in
   `analytics_mart`; ordinary runs update affected keys/grains incrementally.
3. Reload/restart `cube_api` and `cube_refresh_worker` if automatic model reload
   is disabled. Cube/DBHub reporting excludes deleted source rows and exposes
   the four dimensions; current query/rollup caches refresh on a one-minute
   cadence, subject to refresh scheduling/build time.

No `.env`/DSN/port change is needed. MCP clients and the UI discover the updated
Cube dimensions through their existing model-inspection tool.

Incremental staging extracts deleted rows as tombstones. It uses a configurable
48-hour overlapping source-timestamp window with version deduplication; a strict
`_last_updated_at > last_watermark` cursor can miss transactions that commit
late. Derived facts can change when joined payments/returns change without
changing the header's own timestamp. The current incremental fact propagates
changed payment/return keys explicitly. Transactions delayed beyond the
lookback window need reconciliation.

Reference: [PostgreSQL trigger functions](https://www.postgresql.org/docs/current/plpgsql-trigger.html)
and [database clock functions](https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT).
