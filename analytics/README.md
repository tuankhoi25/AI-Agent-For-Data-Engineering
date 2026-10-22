# Maison Douce dbt analytics pipeline

This project turns the operational PostgreSQL schema `bakery` into three
analytics layers:

```text
bakery (PostgreSQL system of record)
  -> analytics_staging  raw copies of all operational tables
  -> analytics_core    current-state conformed tables, bridges and
                       incremental business-grain calculations
  -> analytics_mart   SCD2 dimensions, facts and reporting marts for sales,
                      inventory, customers, procurement, production/waste
                      and cash reconciliation, calendar and daily weather
```

The physical schema names are prefixed by the target schema from
`profiles.yml` because dbt's default `generate_schema_name` behavior is used:
`analytics_staging`, `analytics_core` and `analytics_mart`. The dbt snapshot
tables are technical history stores in `analytics_mart` and are
consumed by the mart SCD2 dimensions.

## Run locally

Scheduled execution uses separate Dagu workflows at staggered times. See the
[Dagu workflow guide](../data_platform/dagu/README.md) for schedules, model
ownership, same-batch dependencies, retries and Marmot catalog synchronization.
The full-batch parent is manual-only. dbt defaults to one thread to reduce
concurrent query memory; `DBT_THREADS` can override it.
Keep the manual runner below for local diagnosis; do not run it alongside
the Dagu writer (stop Dagu and wait for active runs before local execution).

From the project root, check readiness while Docker is stopped:

```bash
./.venv/bin/python analytics/run_pipeline.py --check
./.venv/bin/python -m unittest discover -s analytics/test -v
docker compose --env-file .env -f docker-compose.yml config --quiet
```

The offline check loads `.env`, parses dbt, and verifies that all 35 sources
are in `bakery` and all model/snapshot writes target the three analytics
schemas. It does not connect to PostgreSQL, start Docker or execute ETL.

After starting the platform and completing `generate_script/bootstrap_bakery.sh`,
run one manual ETL batch:

```bash
./.venv/bin/python analytics/run_pipeline.py --run
```

This explicitly requested mode checks pg_duckdb and the 34 audit triggers,
then runs `dbt build --fail-fast` with snapshots and data tests in DAG order.
It compares a daily-sales report using PostgreSQL and DuckDB execution and
checks that the latter actually produces a DuckDB query plan. An exclusive
local lock prevents two copies of this runner from executing together.
It uses the host connection (`DBT_POSTGRES_HOST`, default `localhost`, and
`POSTGRES_HOST_PORT`), matching `profiles.yml`. It never runs the simulator,
starts Docker, drops tables or invokes `--full-refresh` automatically.

The dbt tables persist as regular PostgreSQL tables in `analytics_staging`,
`analytics_core`, and `analytics_mart` on the pg_duckdb-enabled server. The
extension executes analytical SELECTs over those tables; a separate `.duckdb`
database is not required. PostgreSQL executes dbt's transactional MERGE,
snapshot and sequence operations; DuckDB execution is enabled only for the
final reporting check. See the [pg_duckdb documentation](https://github.com/duckdb/pg_duckdb/blob/v1.1.1/README.md).

For direct dbt commands, export `.env` first. Useful selections:

```bash
set -a
. ./.env
set +a
./.venv/bin/dbt build --project-dir analytics --profiles-dir analytics --select tag:staging
./.venv/bin/dbt build --project-dir analytics --profiles-dir analytics --select tag:core+
./.venv/bin/dbt build --project-dir analytics --profiles-dir analytics --select tag:mart
```

An acceptance run on live data still needs a second unchanged batch to prove
idempotency, source-to-staging/core row reconciliation, fact-to-mart totals,
and stable dimension SKs. The fixture checks exercise SQL behavior in memory;
they do not replace validation on PostgreSQL with the actual bakery data.

The first live acceptance on 2026-10-22 is recorded in
`MANUAL_VALIDATION_2026-10-22.md`. To repeat the read-only reconciliation after
a successful build and compare two unchanged runs:

```bash
./.venv/bin/python analytics/validate_pipeline.py --output analytics/target/manual_baseline.json
./.venv/bin/python analytics/run_pipeline.py --run
./.venv/bin/python analytics/validate_pipeline.py --compare analytics/target/manual_baseline.json --output analytics/target/manual_validation.json
```

The comparison fingerprints all source/target rows and dimension sequences.
Use it with a stable source: legitimate new operational writes should change
the fingerprints. The PostgreSQL return fixture can also be run after a build
using `./.venv/bin/python analytics/test/validate_return_fixture.py`; it uses
the actual compiled incremental fact SQL, writes only transaction-local TEMP
rows and rolls back everything.

Computed core/mart numeric outputs explicitly use `numeric(38,9)` for
pg_duckdb compatibility. Quantities and money stay decimal, rather than being
converted to floating point. Derived averages/durations are rounded to nine
fractional digits. Source columns retain their declared precision. Report
validation runs in a read-only autocommit connection and verifies the actual
DuckDB plan, rather than merely checking that `force_execution` is enabled.

`mart_daily_operations` has grain `(business_date, branch_id, uom_id)`;
production/waste quantities in different units must not be added together.

The core layer deliberately keeps the operational grain visible:

- receipt totals are not joined directly to sale lines without aggregation;
- historical sale-line name, unit and price snapshots are retained;
- payment attempts, completed returns and loyalty transactions are separate;
- inventory balance is derived from signed `stock_movements`, not from the
  existence of `inventory_lots`;
- procurement quantity comparisons are only made when ordered and received
  units match;
- planned production is not treated as actual output.

Dimension history and fact keys:

- `dim_allergens`, `dim_branches`, `dim_customers`, `dim_employees`,
  `dim_inventory_lots`, `dim_product_categories`, `dim_products`,
  `dim_promotions`, `dim_recipes`, `dim_stock_items`, `dim_suppliers` and
  `dim_units_of_measure` in `mart` are SCD2 dimensions;
- each dimension has a durable numeric `*_sk`, the source business key,
  `_valid_from`, `_valid_to`, `_observed_from` and `_is_current`;
- `fct_sales` and `fct_sale_items` in `mart` resolve `branch_sk`, `customer_sk`, `employee_sk`,
  `product_sk` and `uom_sk` against the dimension version valid at the sale
  timestamp; business keys remain only for traceability;
- snapshots are sourced from the latest row per business key in staging and
  are materialized into `analytics_mart`. The numeric SK is
  assigned from a PostgreSQL sequence and is preserved across incremental
  runs;
- `_observed_from` retains the original snapshot timestamp. The first observed
  version has effective `_valid_from = '-infinity'` so historical backfill
  events resolve a dimension key even when they predate database insertion.
  This explicitly assumes the first observed attributes for earlier events;
  their actual earlier price/name/UOM history cannot be reconstructed from
  a current-state source. Later versions use their actual snapshot timestamp.
  Treat events before `_observed_from` as inferred descriptive history when
  analyzing historical changes;
- SCD2 does not provide unit conversion by itself. The current operational
  UOM table still has no general conversion factor, so `BOX`/`PACK`/`BOTTLE`
  comparisons require a versioned product-to-UOM conversion rule before
  normalized quantity or price-per-base-unit can be calculated.
- `dim_date` is a Type 0 calendar dimension keyed by `date_sk` (`YYYYMMDD`),
  while `fct_daily_weather` stores one detailed weather observation per date,
  location and source and links to `dim_date`.

The custom data tests cover sales amount reconciliation, return quantities,
inventory-movement signs, exactly one current dimension version, non-overlapping
SCD2 intervals and fact SK/business-key/validity consistency.
The business rules in `BUSINESS_LOGIC.md` remain the
authoritative interpretation when a source record is incomplete or ambiguous.

## Source audit fields and soft deletion

The 34 audited operational sources carry `_created_at`, `_last_updated_at`,
`_is_deleted`, `_deleted_at`; the simulator control table is excluded.
Staging deliberately keeps every source row including tombstones. Each core
model selects the latest source version per business key and retains the
latest tombstone row so that a source deletion, or a change to a joined
dimension, can be propagated without scanning and rebuilding the whole core
table. Reporting models filter `_is_deleted` rows before aggregating. Core
models also stamp `_source_ingested_at` and `_record_updated_at`; the latter
is the maximum change watermark of the row and its joined dependencies.

The staging layer is append-only incremental for the 34 audited operational
tables. Each extracted row carries `_ingested_at`, `_batch_id` and
`_source_last_updated_at`. The source audit trigger supplies
`_last_updated_at`. Each incremental extraction rechecks the last 48 hours
relative to the loaded source high watermark (`staging_lookback_hours`) and
skips already loaded `(business key, _source_last_updated_at)` versions.
This catches ordinary late commits without appending unchanged rows. A
transaction delayed beyond that window still needs reconciliation or a
deliberately larger lookback; it is not commit-order CDC. Unique version,
source watermark and ingestion indexes support these operations. Core
models merge only newly ingested business keys and
keys affected by changed dependencies. Core is therefore incremental by
default; no current core calculation requires a whole-table overwrite. The
loyalty balance window is recomputed incrementally by affected customer
partition. Mart dimensions close/open only the affected SCD2 versions, facts
recompute affected sale or sale-line keys, and aggregate marts delete and
rebuild only affected reporting grains before merging them back.
`simulation_runs` is a generator-control table and remains a full table model
because it is intentionally outside the row-audit contract. Use
`--full-refresh` only after deliberately changing a model contract or when
rebuilding history.
The loyalty balance window is the one non-row-local core calculation: only
customers affected by new, changed or deleted loyalty inputs are recomputed.
Run `dbt build` so snapshots are processed before their SCD2 dimension models;
the first snapshot run establishes the initial dimension versions.

Logical deletion does not cascade. Deleting a parent does not mark its children
or stock/cash/point ledger rows deleted. Apply consistent business corrections
and logical-deletion changes together. Historical transactions retain their
own row audit state even if a descriptive master is unavailable.

## Rebuild scope during manual acceptance

If existing derived tables use the old snapshot schema or validity contract,
inspect them before the first live acceptance run. A deliberate rebuild can
remove only explicitly identified ETL tables/sequences in the analytics
schemas and confirmed legacy `core.snap_dim_*` snapshot tables. Preserve
`bakery`, `marmot`, `cube_core`, extension objects, unrelated schemas and the
PostgreSQL Docker volume. In particular, do not use `docker compose down -v`
to reset analytics. Rebuilding snapshots discards their captured SCD2 history,
so it must be an intentional acceptance reset, not the daily run procedure.
