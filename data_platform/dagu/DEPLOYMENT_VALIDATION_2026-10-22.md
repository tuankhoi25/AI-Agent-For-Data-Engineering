# Dagu deployment validation — 2026-10-22

This archive records validation runs from the earlier parent-DAG layout. The
active deployment now uses the separate component DAGs documented in
`data_platform/dagu/README.md`.

## Result

Prefect was replaced by Dagu 2.21.0, deployed and tested against the running
Bakery platform. Method A was evaluated against the pinned Dagu API and the
live Marmot REST API, then implemented successfully without forking either
product. Source generation remains manual.

One Dagu container replaces the three Prefect services. Dagu state, scheduler,
queue, logs and sync ownership ledger use `bakery_dagu_data`; there is no new
metadata database. UI/API: http://localhost:8088, loopback-bound, local-only
auth-none configuration. DAG definitions mount read-only; wiki/state use the
writable Dagu volume. Image includes checksum-pinned Dagu binary and pinned
dbt/Python dependencies; no Prefect SDK.

## Active DAGs

The active deployment now uses the component DAGs below; each is scheduled
independently on the shared `bakery` queue, with global max_concurrency 1.

| DAG | Schedule | Tasks |
|---|---|---|
| weather-daily | 22:00 daily, Asia/Ho_Chi_Minh | Collect completed daily weather. |
| source-core | 22:15 daily | Preflight, source phases, scoped tests and component publication. |
| dimensions-reference | 22:30 daily | Build, scoped tests and publish reference dimensions. |
| dimensions-parties | 22:40 daily | Build, scoped tests and publish party dimensions. |
| dimensions-products | 22:50 daily | Build, scoped tests and publish product dimensions. |
| facts-sales | 23:05 daily | Build, scoped tests and publish sales facts. |
| facts-weather | 23:15 daily | Build, scoped tests and publish weather facts. |
| marts-sales | 23:25 daily | Build, scoped tests and publish sales marts. |
| marts-operations | 23:35 daily | Build, scoped tests and publish operations marts. |

Manual acceptance runs used the API enqueue endpoint, not direct `dagu start`.
Deep audit was explicitly enabled on the acceptance ETL runs.

## Live execution evidence

| Run ID | DAG | Result |
|---|---|---|
| 034kCsllDWrljFtAYsPZCA | bakery-dbt-daily | Succeeded, 14:13:25–14:14:12 +07:00. |
| 034kCwh2PSaIcPvYw8Sh9l | bakery-dbt-daily | Succeeded, 14:14:45–14:15:29 +07:00. |
| 034kD4VqIwQgmQy1hI4ZHb | bakery-dbt-daily | Succeeded, finished 14:20:40 +07:00; validated final per-attempt catalog publication. |
| 034kCzjGpJk1kEwNYO2oFX | bakery-catalog-sync | Succeeded, 14:16:44–14:17:05 +07:00. |
| 034kD6ivh5tQ3Vj60NSLWK | bakery-catalog-sync | Succeeded, 14:21:20–14:21:41 +07:00; ingested final successful artifacts. |

Initial setup run `034kCqtFwKyyonAUCJFWow` failed at preflight because Dagu
does not pass arbitrary process environment into tasks. This was fixed with
an explicit `env_passthrough` allowlist; secrets are referenced from Compose,
not written into DAG YAML/params. Its genuine failure remains visible in run
history. The interrupted run was eventually marked failed by Dagu; no ETL
write phase ran in that failed setup attempt.

## Data acceptance

- Preflight: 34 Bakery source tables, 33 audited business-table triggers,
  pg_duckdb 1.1.0; targets restricted to the three analytics schemas.
- All seven dbt command phases passed. Published aggregate: 100 successful
  model/snapshot resources plus 160 passed unique tests = 260 resources.
- Read-only validator: 110 reconciliation checks passed; 146 source, target
  and SK-sequence fingerprints identical to baseline after repeated runs.
- DuckDB actually planned and read all columns of all 100 target tables;
  report results matched PostgreSQL.
- Source sales: 834 orders, business dates 2026-10-05 through 2026-10-21,
  revenue 154,911,400 VND. No source mutation, DROP, full-refresh, sequence
  reset or snapshot/history rebuild was needed.
- Baseline and comparisons: `analytics/target/dagu/before.json`,
  `after_first.json`, `after_second.json`, `final_validation.json`.

Successful artifacts are isolated by run and publish attempt. The final
pointer resolves to:
`runs/034kD4VqIwQgmQy1hI4ZHb/publish-artifacts/attempt-1/catalog`.
Only successful complete quality gates can advance `latest_success.json`.
An upstream retry invalidates its old success marker and downstream markers;
failed reruns cannot reuse stale gates or overwrite the last published catalog.

## Marmot acceptance — Method A

- Dagu API → allowlisted Python mapping → Marmot REST batch API.
  Full DAG-list pagination, YAML spec dependency validation, stable IDs,
  instance/project ownership boundaries and fail-closed empty/error handling.
- Exactly 2 Dagu Pipeline assets, 13 Task assets, and 24 intended graph edges
  were created and verified by reading the resulting Marmot graph.
- Schedules, Asia/Ho_Chi_Minh timezone, suspended=false and next run times
  22:15/22:45 were verified from live Dagu metadata.
- Marmot ETL run history: 4 stable run identities, 3 COMPLETE and 1 FAIL,
  with real start/end timestamps. Repeated sync did not duplicate identities.
- Live stale-edge test: injected one extra catalog-only edge under the
  adapter's ownership. First sync removed exactly 1 stale edge; repeated sync
  removed 0. Legitimate 24 edges remained. No execution DAG was changed.
- Removed/renamed asset retirement and protection of foreign-owned edges
  were verified with a fake API unit test, not by deleting live Bakery DAGs.
- Native Marmot dbt plugin ingestion passed. Independent lookup verified
  100 physical target tables, 88 dbt model assets and all 12
  staging → snapshot → dimension paths. Existing snapshot compatibility
  adapter retained because plugin 0.1.1 skips snapshot resources.
- Dagu dependencies are not represented as table lineage. No fabricated
  task-to-model execution mapping, raw command, environment, params, log
  content or credentials are exported.

Poll-based limitation: metadata reflects `observed_at`, not real-time state.
The catalog DAG can observe itself Running; its completed state appears at
the next sync. Run history is capped to the latest 20 returned runs per DAG.
The instance timezone is shared by both managed DAGs. More complex DAGs
(sub-DAGs, dynamic dependencies, alternate timezones) need an explicit mapping
extension rather than being silently inferred. Marmot is built from the
upstream v0.11.1 source with a small `providerIconMap` customization, so
provider Dagu displays its Dagu logo in the UI.

## Tests and deployment checks

- 12 adapter/artifact-safety unit tests passed: pagination, empty snapshot,
  invalid dependencies, identity collisions, static graph without runs,
  timestamps/stable run IDs, stale-edge pruning, retirement, foreign edge
  protection, unsafe run IDs, retry invalidation, publication gates.
- 8 existing analytics incremental/SCD2 contract unit tests passed.
- Both DAGs validated with the actual pinned Dagu binary.
- `docker compose config --quiet` passed; Dagu container healthy.
- Server uses explicit env passthrough. No secret values were published or
  recorded in this report.

## Prefect retirement and retained history

The three stopped Prefect containers were removed **without volumes**.
`bakery_prefect_db_data` still exists and was checked. The old implementation
and report remain in `data_platform/prefect/` as an inactive rollback archive,
not mounted into Dagu or installed in its image.

The old native Marmot `bakery-prefect` ingestion schedule remains disabled;
13 old Prefect assets were marked lifecycle=retired, replaced_by=Dagu. Their
run history is retained. The existing `bakery-dbt-artifacts` schedule was
updated in place to the Dagu artifact mount and remains disabled on Marmot
because Dagu owns its schedule. Existing PostgreSQL ingestion/enrichment and
unrelated services were not changed.

No recurring log/artifact cleanup has been installed. Keep both the Dagu
volume (including ownership ledger) and successful dbt artifacts backed up;
set a retention policy separately as history grows. Do not use `down -v` for
a normal restart.

## References

- [Dagu REST API](https://docs.dagu.sh/web-ui/api)
- [Pinned Dagu 2.21.0 API schema](https://github.com/dagucloud/dagu/blob/v2.21.0/api/v1/api.yaml)
- [Dagu dbt remote action](https://docs.dagu.sh/dagu-actions/official/dbt)
- [Marmot ingestion methods](https://marmotdata.io/docs/Populating/)
