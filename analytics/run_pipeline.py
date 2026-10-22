#!/usr/bin/env python3
"""Offline readiness check, or one explicitly requested manual dbt build."""

import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from dotenv import load_dotenv
import psycopg


PROJECT = Path(__file__).resolve().parent
ROOT = PROJECT.parent
ALLOWED_SCHEMAS = {"analytics_staging", "analytics_core", "analytics_mart"}


def dbt(*args):
    executable = ROOT / ".venv/bin/dbt"
    if not executable.is_file():
        raise RuntimeError("Install the project requirements into .venv first.")
    subprocess.run(
        [str(executable), *args, "--project-dir", str(PROJECT),
         "--profiles-dir", str(PROJECT)],
        cwd=ROOT, check=True,
    )


def check_manifest():
    manifest = json.loads((PROJECT / "target/manifest.json").read_text())
    resources = [n for n in manifest["nodes"].values()
                 if n["resource_type"] in {"model", "snapshot"}]
    for node in resources:
        if node["schema"] not in ALLOWED_SCHEMAS:
            raise RuntimeError(f"Unexpected ETL target: {node['relation_name']}")
        if node["resource_type"] == "snapshot" and node["schema"] != "analytics_mart":
            raise RuntimeError(f"Snapshot outside mart: {node['name']}")
    sources = list(manifest["sources"].values())
    if len(sources) != 35 or any(s["schema"] != "bakery" for s in sources):
        raise RuntimeError("The pipeline must read exactly the 35 bakery sources.")
    if manifest.get("semantic_models") or manifest.get("metrics"):
        raise RuntimeError("Unexpected Semantic Layer resources.")
    for (kind, schema), count in sorted(Counter(
        (n["resource_type"], n["schema"]) for n in resources
    ).items()):
        print(f"{schema}: {count} {kind}s", flush=True)
    return sources


def connect():
    # This mirrors profiles.yml: host-published port, not Docker's service port.
    return psycopg.connect(
        host=os.getenv("DBT_POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_HOST_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=10,
        application_name="bakery_manual_etl_check",
        options="-c default_transaction_read_only=on -c duckdb.force_execution=off",
    )


def check_live_source(sources):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("show server_version_num")
        if int(cur.fetchone()[0]) < 150000:
            raise RuntimeError("PostgreSQL 15+ is required for incremental MERGE.")
        cur.execute("select extversion from pg_extension where extname = 'pg_duckdb'")
        extension = cur.fetchone()
        if not extension:
            raise RuntimeError("pg_duckdb is not installed in the target database.")
        cur.execute("show shared_preload_libraries")
        if "pg_duckdb" not in {lib.strip() for lib in cur.fetchone()[0].split(",")}:
            raise RuntimeError("pg_duckdb must be preloaded; check Compose.")
        for source in sources:
            table = source["identifier"]
            cur.execute("""
                select column_name, data_type, is_nullable
                from information_schema.columns
                where table_schema = 'bakery' and table_name = %s
            """, (table,))
            columns = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
            if not columns:
                raise RuntimeError(f"Missing source bakery.{table}; run bootstrap first.")
            if table == "simulation_runs":
                continue
            expected = {
                "_created_at": ("timestamp with time zone", "NO"),
                "_last_updated_at": ("timestamp with time zone", "NO"),
                "_is_deleted": ("boolean", "NO"),
                "_deleted_at": ("timestamp with time zone", "YES"),
            }
            for column, contract in expected.items():
                if columns.get(column) != contract:
                    raise RuntimeError(f"Incorrect audit column bakery.{table}.{column}")
            cur.execute("""
                select count(*) from pg_trigger t
                join pg_class c on c.oid = t.tgrelid
                join pg_namespace n on n.oid = c.relnamespace
                join pg_proc p on p.oid = t.tgfoid
                join pg_namespace pn on pn.oid = p.pronamespace
                where n.nspname = 'bakery' and c.relname = %s
                  and not t.tgisinternal and t.tgenabled in ('O', 'A')
                  and pn.nspname = 'bakery' and p.proname = 'set_row_audit'
                  and t.tgtype = 23 -- BEFORE INSERT OR UPDATE FOR EACH ROW
            """, (table,))
            if cur.fetchone()[0] != 1:
                raise RuntimeError(f"Missing/enabled audit trigger mismatch: bakery.{table}")
        print(f"Source preflight passed: 35 tables, 34 audit triggers; pg_duckdb {extension[0]}.", flush=True)


def check_duckdb_reporting():
    query = """
        select business_date, branch_id,
               sum(order_count) as order_count,
               round(sum(receipt_revenue), 2) as revenue
        from analytics_mart.mart_daily_sales
        group by business_date, branch_id
        order by business_date, branch_id
    """
    conn = connect()
    # pg_duckdb 1.1 does not route this report to DuckDB inside an explicit
    # PostgreSQL transaction. Each autocommit statement remains read-only via
    # the connection's default_transaction_read_only setting.
    conn.autocommit = True
    with conn, conn.cursor() as cur:
        cur.execute(query)
        postgres_rows = cur.fetchall()
        cur.execute("set duckdb.force_execution = true")
        cur.execute("explain " + query)
        plan = "\n".join(row[0] for row in cur.fetchall())
        if "duckdb" not in plan.lower():
            raise RuntimeError("Reporting query did not produce a DuckDB query plan.")
        cur.execute(query)
        if cur.fetchall() != postgres_rows:
            raise RuntimeError("PostgreSQL and DuckDB reporting results differ.")
        print(f"pg_duckdb reporting parity passed for {len(postgres_rows)} branch/day rows.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Offline parse and target checks; no DB connection")
    mode.add_argument("--run", action="store_true", help="Preflight, dbt build/tests, then pg_duckdb parity")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    # dbt's PostgreSQL DDL/MERGE/snapshot transactions use PostgreSQL execution.
    # The final read-only reporting check explicitly enables DuckDB.
    os.environ["PGOPTIONS"] = os.environ.get("PGOPTIONS", "") + " -c duckdb.force_execution=off -c timezone=Asia/Ho_Chi_Minh"
    (PROJECT / "target").mkdir(exist_ok=True)
    with (PROJECT / "target/manual_pipeline.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another manual pipeline command is already running.") from None
        dbt("parse", "--no-partial-parse")
        sources = check_manifest()
        if args.check:
            print("Offline checks passed. No ETL was executed and no DB was contacted.")
            return
        check_live_source(sources)
        dbt("build", "--fail-fast")
        check_duckdb_reporting()
        print("Manual ETL completed. See analytics/target/run_results.json for model/test results.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, psycopg.Error, subprocess.CalledProcessError) as exc:
        # Avoid printing driver errors/DSNs, which can contain connection secrets.
        if isinstance(exc, psycopg.Error):
            print("Database check failed. Verify Docker, bootstrap and local connection settings.", file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        sys.exit(1)
