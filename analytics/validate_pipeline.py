#!/usr/bin/env python3
"""Read-only live reconciliation and repeat-run fingerprint validation."""

import argparse
from datetime import datetime
import json
from pathlib import Path

from dotenv import load_dotenv
from psycopg import sql

from run_pipeline import PROJECT, ROOT, connect


def ident(*parts):
    return sql.Identifier(*parts).as_string()


def reconcile(cur, name, expected, actual, results):
    cur.execute(f"""
        with expected as ({expected}), actual as ({actual})
        select count(*) from (
            (select * from expected except all select * from actual)
            union all
            (select * from actual except all select * from expected)
        ) differences
    """)
    count = cur.fetchone()[0]
    results[name] = count
    if count:
        raise RuntimeError(f"{name}: {count} mismatching rows")


def fingerprints(cur, manifest):
    state = {}
    resources = list(manifest["sources"].values()) + [
        n for n in manifest["nodes"].values()
        if n["resource_type"] in {"model", "snapshot"}
    ]
    for node in resources:
        relation = ident(node["schema"], node.get("alias") or node["identifier"])
        cur.execute(f"""
            select count(*), md5(coalesce(string_agg(row_hash, '' order by row_hash), ''))
            from (select md5(to_jsonb(t)::text) row_hash from {relation} t) rows
        """)
        rows, digest = cur.fetchone()
        state[node["schema"] + "." + (node.get("alias") or node["identifier"])] = {
            "rows": rows, "hash": digest,
        }
    cur.execute("""
        select schemaname, sequencename, last_value
        from pg_sequences where schemaname = 'analytics_mart'
        order by sequencename
    """)
    for schema, name, value in cur.fetchall():
        state[f"{schema}.{name}"] = {"last_value": value}
    return state


def run_checks(cur):
    results = {}
    # dbt stores project variables on nodes, not in the manifest root.
    import yaml
    variables = yaml.safe_load((PROJECT / "dbt_project.yml").read_text())["vars"]
    for model, keys in variables["staging_business_keys"].items():
        table = model.removeprefix("stg_")
        source = ident("bakery", table)
        staging = ident("analytics_staging", model)
        core = ident("analytics_core", "core_" + table)
        columns = ", ".join(ident(key) for key in keys)
        reconcile(cur, f"source_staging:{table}",
            f"select to_jsonb(s) from {source} s",
            f"""select to_jsonb(s) - array['_ingested_at','_batch_id','_source_last_updated_at']
                from (select distinct on ({columns}) * from {staging}
                      order by {columns}, _source_last_updated_at desc,
                               _ingested_at desc, _batch_id desc) s""", results)
        reconcile(cur, f"source_core:{table}",
            f"select {columns}, _last_updated_at, _is_deleted from {source}",
            f"select {columns}, _source_last_updated_at, _is_deleted from {core}", results)
        cur.execute(f"select count(*) from (select {columns} from {core} group by {columns} having count(*) > 1) duplicates")
        results[f"core_grain:{table}"] = cur.fetchone()[0]
        if results[f"core_grain:{table}"]:
            raise RuntimeError(f"Duplicate business keys in {core}")

    reconcile(cur, "simulation_runs",
        "select to_jsonb(t) from bakery.simulation_runs t",
        "select to_jsonb(t) from analytics_staging.stg_simulation_runs t", results)
    reconcile(cur, "sales_fact",
        "select sale_id,total_amount,_is_deleted from bakery.sales",
        "select sale_id,total_amount,_is_deleted from analytics_mart.fct_sales", results)
    reconcile(cur, "sale_line_fact",
        "select sale_item_id,line_total,quantity,_is_deleted from bakery.sale_items",
        "select sale_item_id,line_total,sold_quantity,_is_deleted from analytics_mart.fct_sale_items", results)
    reconcile(cur, "daily_sales",
        """select (coalesce(completed_at,opened_at) at time zone 'Asia/Ho_Chi_Minh')::date,
                  branch_id,count(*),sum(subtotal),sum(discount_total),sum(tax_total),sum(total_amount)
           from bakery.sales where not _is_deleted
             and status in ('COMPLETED','PARTIALLY_REFUNDED','REFUNDED') group by 1,2""",
        """select business_date,branch_id,order_count,gross_sales,discount_amount,tax_amount,receipt_revenue
           from analytics_mart.mart_daily_sales""", results)
    reconcile(cur, "product_sales",
        """select (coalesce(s.completed_at,s.opened_at) at time zone 'Asia/Ho_Chi_Minh')::date,
                  s.branch_id,i.product_id,u.uom_code,sum(i.quantity),sum(i.line_total),count(*)
           from bakery.sale_items i join bakery.sales s using(sale_id)
           join bakery.units_of_measure u using(uom_id)
           where not i._is_deleted and not s._is_deleted
             and s.status in ('COMPLETED','PARTIALLY_REFUNDED','REFUNDED') group by 1,2,3,4""",
        """select business_date,branch_id,product_id,uom_code,sold_quantity,
                  net_line_sales_before_refund,sale_line_count
           from analytics_mart.mart_product_sales""", results)
    reconcile(cur, "inventory_balance",
        """select branch_id,stock_item_id,inventory_lot_id,sum(quantity_delta)
           from bakery.stock_movements where not _is_deleted group by 1,2,3""",
        """select branch_id,stock_item_id,inventory_lot_id,on_hand_quantity
           from analytics_mart.mart_inventory_position""", results)
    reconcile(cur, "customer_points",
        """select c.customer_id,coalesce(sum(l.points_delta) filter(where not l._is_deleted),0)
           from bakery.customers c left join bakery.loyalty_transactions l using(customer_id)
           where not c._is_deleted group by c.customer_id""",
        "select customer_id,current_points_balance from analytics_mart.mart_customer_360", results)
    reconcile(cur, "cash_balance",
        """select s.shift_id,s.opening_cash + coalesce(sum(case
                 when m.movement_type in ('FLOAT_IN','SALE_CASH_IN','OTHER_IN') then m.amount
                 else -m.amount end) filter(where not m._is_deleted),0)
           from bakery.shifts s left join bakery.cash_movements m using(shift_id)
           where not s._is_deleted group by s.shift_id,s.opening_cash""",
        "select shift_id,expected_ending_cash from analytics_mart.mart_cash_reconciliation", results)
    reconcile(cur, "production_by_unit",
        """select (coalesce(completed_at,started_at) at time zone 'Asia/Ho_Chi_Minh')::date,
                  branch_id,uom_id,count(*),sum(planned_quantity),sum(produced_quantity)
           from bakery.production_batches where not _is_deleted and status='COMPLETED'
             and completed_at is not null group by 1,2,3""",
        """select business_date,branch_id,uom_id,completed_batch_count,planned_output_quantity,produced_output_quantity
           from analytics_mart.mart_daily_operations where completed_batch_count > 0""", results)
    reconcile(cur, "waste_by_unit",
        """select (recorded_at at time zone 'Asia/Ho_Chi_Minh')::date,branch_id,uom_id,count(*),sum(quantity)
           from bakery.waste_records where not _is_deleted group by 1,2,3""",
        """select business_date,branch_id,uom_id,waste_record_count,wasted_quantity
           from analytics_mart.mart_daily_operations where waste_record_count > 0""", results)
    cur.execute("""
        select table_schema,table_name,column_name from information_schema.columns
        where table_schema in ('analytics_staging','analytics_core','analytics_mart')
          and data_type='numeric' and numeric_precision is null
    """)
    unbounded = cur.fetchall()
    if unbounded:
        raise RuntimeError(f"DuckDB-incompatible numeric columns: {unbounded}")
    results["unbounded_numeric_columns"] = 0
    return results


def check_duckdb_targets(manifest):
    conn = connect()
    conn.autocommit = True
    count = 0
    with conn, conn.cursor() as cur:
        cur.execute("set duckdb.force_execution = true")
        for node in manifest["nodes"].values():
            if node["resource_type"] not in {"model", "snapshot"}:
                continue
            relation = ident(node["schema"], node["alias"])
            query = f"select * from {relation} limit 1"
            cur.execute("explain " + query)
            if "duckdb" not in "\n".join(r[0] for r in cur.fetchall()).lower():
                raise RuntimeError(f"DuckDB cannot plan all columns of {relation}")
            cur.execute(query)
            # Execute each projection, without decoding +/-infinity timestamps
            # into Python datetimes (not supported by psycopg's datetime type).
            count += 1
    return count


def check_source_preserved(manifest, path):
    previous = json.loads(path.read_text())
    with connect() as conn, conn.cursor() as cur:
        for source in manifest["sources"].values():
            table = source["identifier"]
            cur.execute(f"""
                select count(*),md5(coalesce(string_agg(h,'' order by h),''))
                from (select md5(to_jsonb(t)::text) h from {ident('bakery',table)} t) rows
            """)
            if list(cur.fetchone()) != previous[table]:
                raise RuntimeError(f"Source changed since acceptance rebuild: bakery.{table}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path, help="Baseline to compare all source/target rows and SK sequences")
    parser.add_argument("--source-baseline", type=Path, help="Verify source fingerprints captured before target rebuild")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    manifest = json.loads((PROJECT / "target/manifest.json").read_text())
    with connect() as conn, conn.cursor() as cur:
        cur.execute("set transaction isolation level repeatable read")
        cur.execute("set local timezone = 'Asia/Ho_Chi_Minh'")
        checks = run_checks(cur)
        state = fingerprints(cur, manifest)
        cur.execute("""select count(*), min(business_date), max(business_date),sum(total_amount)
                       from analytics_mart.fct_sales where not _is_deleted and is_sale_completed""")
        sales = cur.fetchone()
        cur.execute("select count(*) from bakery.returns where not _is_deleted")
        returns_count = cur.fetchone()[0]
    report = {"generated_at": datetime.now().astimezone().isoformat(),
              "checks": checks, "state": state,
              "sales": {"orders": sales[0], "from": str(sales[1]), "to": str(sales[2]), "revenue": str(sales[3])},
              "return_documents": returns_count}
    report["duckdb_readable_targets"] = check_duckdb_targets(manifest)
    if args.source_baseline:
        check_source_preserved(manifest, args.source_baseline)
        report["source_preserved_since_rebuild"] = True
    if args.compare:
        previous = json.loads(args.compare.read_text())["state"]
        changed = [name for name in set(previous) | set(state) if previous.get(name) != state.get(name)]
        report["unchanged_baseline"] = not changed
        if changed:
            raise RuntimeError(f"Repeat-run fingerprints changed: {sorted(changed)}")
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: {len(checks)} reconciliation checks; {len(state)} source/target/sequence fingerprints.")
    print(json.dumps(report["sales"]))
    print(f"Return documents available for testing: {returns_count}")
    print(f"PASS: DuckDB planned/executed all columns of {report['duckdb_readable_targets']} ETL tables.")
    if args.source_baseline:
        print("PASS: all 35 bakery source tables are unchanged since the target rebuild.")
    if args.compare:
        print("PASS: all source/target content and SK sequences unchanged after rerun.")


if __name__ == "__main__":
    main()
