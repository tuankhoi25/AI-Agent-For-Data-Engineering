# Bakery catalog enrichment

The Compose service builds Marmot v0.11.1 from the upstream source with one
small frontend customization: the Dagu provider icon is registered in
`providerIconMap`. Dagu orchestration metadata is synchronized through a
small Python REST adapter (method A). See the repository-root Data pipeline
section for schedules and operating instructions.

The custom build is reproducible from `Dockerfile` and
`dagu-iconloader.patch`. It uses the `selfhst:dagu` Iconify asset already
available through Marmot's pinned frontend icon bundle. Rebuilding the image
does not touch the Marmot/PostgreSQL data volume.

`enrich_bakery_metadata.py` reads `MARMOT_HOST` and `MARMOT_API_KEY` from the
project-root `.env`. It updates the already-synchronized operational assets;
it does not modify PostgreSQL business records.

Run from the repository root:

```bash
python3 data_platform/marmot/enrich_bakery_metadata.py --dry-run
python3 data_platform/marmot/enrich_bakery_metadata.py
```

## Definition sources

- `data_platform/postgres/*.sql`: declared column types, NULL/default rules,
  identity, primary/unique/foreign keys, CHECK expressions and allowed values.
- `bakery_metadata_details.py`: column-specific meanings, value meanings,
  table-level calculation rules and metric glossary definitions.
- `generate_script/simulate_operations.py`: current application behavior,
  including discounts, loyalty, returns, quantities, dates and costs.
- `enrich_bakery_metadata.py`: asset summaries, entity glossary, product
  groupings and Marmot API integration.

SQL-enforced constraints and application conventions are documented separately.
The declared contracts describe the repository DDL, not a live constraint
introspection service. Business metadata is English; original database values,
including product names, are retained.

## Published content

All 34 audited operational tables and 462 current columns (including 136 record-lifecycle fields) have business descriptions.
Schema Content includes value meanings, units/currency, NULL/default semantics,
keys and constraints. Visible asset documentation pages include the same
definitions plus table-level rules. Forty glossary terms include entity
concepts and 16 metric definitions with formulas, units, synonyms and source
tables. Four data products describe their scope and calculation limitations.

`asset.schema` is a map of named schema documents. Its native PostgreSQL section
is `columns`, containing a JSON array of column objects with `column_name` and
`data_type`. Do not add descriptions, business-rule lists, paths or constraint
objects as separate keys in that map: Marmot attempts to parse every key as a
schema. Table-level descriptions/rules/constraints belong in asset metadata and
documentation; column descriptions stay inside the `columns` document. The
script removes the four invalid schema sections written by older versions.

The script checks definition coverage and complete connector column schemas
before writing. A new CHECK value without a corresponding business meaning
causes an error instead of silently producing incomplete metadata. After a
schema change, synchronize PostgreSQL metadata first and update the authored
definitions as required. Existing script-managed glossary terms and pages are
updated by name; unrelated catalog content is retained.

`simulation_runs` is a generator control table and is excluded from the
operational catalog. The enrichment script also removes its legacy catalog
definitions. Tax rates, labor/overhead costs, physical cash counts and general
unit conversion factors are not invented when the source does not define them.

## Record lifecycle fields

Every operational table has `_created_at`, `_last_updated_at`, `_is_deleted`
and `_deleted_at`. English column descriptions, value meanings, table rules,
asset metadata (`record_lifecycle`) and visible documentation explain trigger
ownership, soft deletion/restoration, migration adoption time and the distinction
between database write time and historical business event time. Existing
`created_at` fields on branches/products remain separate legacy columns.

Initialize the PostgreSQL source with the numbered SQL scripts, then **run the
ingestion pipeline** to refresh column schemas before enrichment. Registering
or updating a scheduled pipeline alone does not execute ingestion. Enrichment
intentionally rejects an old 293-column catalog rather than inventing source
columns; after sync it expects 462 columns across 34 tables. The ingestion
configuration already includes all columns and needs no new table names.
