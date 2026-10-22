#!/usr/bin/env python3
"""Exercise real compiled incremental fact SQL with transaction-local returns.

Only pg_temp tables are written, and the entire transaction is rolled back.
No operational row, persisted fact, dimension or snapshot is changed.
"""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from run_pipeline import PROJECT, ROOT, connect


def main():
    load_dotenv(ROOT / ".env", override=False)
    manifest = json.loads((PROJECT / "target/manifest.json").read_text())
    actual_returns = manifest["nodes"]["model.analytics.core_return_items"]["relation_name"]
    queries = {}
    for name in ("fct_sales", "fct_sale_items"):
        node = manifest["nodes"]["model.analytics." + name]
        queries[name] = node["compiled_code"].replace(actual_returns, "pg_temp.fixture_returns")
    conn = connect()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("set default_transaction_read_only = off")
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                select sale_id,sale_item_id,line_total / sold_quantity
                from analytics_mart.fct_sale_items
                where is_sale_completed and not _is_deleted and sold_quantity >= 1
                order by sale_item_id limit 1
            """)
            sale_id, item_id, refund = cur.fetchone()
            cur.execute("""create temporary table fixture_returns on commit drop as
                           select * from analytics_core.core_return_items where false""")
            cur.execute("""
                insert into fixture_returns
                    (return_item_id,sale_id,sale_item_id,quantity,refund_amount,
                     restockable,is_completed_return,_is_deleted,_record_updated_at)
                values (-1,%s,%s,1,%s,true,true,false,clock_timestamp())
            """, (sale_id, item_id, refund))
            for state in ("completed", "cancelled", "soft_deleted"):
                if state == "cancelled":
                    cur.execute("update fixture_returns set is_completed_return=false,_record_updated_at=clock_timestamp()")
                elif state == "soft_deleted":
                    cur.execute("update fixture_returns set is_completed_return=true,_is_deleted=true,_record_updated_at=clock_timestamp()")
                for name, query in queries.items():
                    amount = "total_amount" if name == "fct_sales" else "line_total"
                    net = "revenue_after_refund" if name == "fct_sales" else "net_line_sales_after_refund"
                    cur.execute(f"select refund_amount,{net},{amount},returned_quantity from ({query}) result")
                    rows = cur.fetchall()
                    if len(rows) != 1:
                        raise RuntimeError(f"{name}/{state}: expected one affected fact, got {len(rows)}")
                    row_refund, row_net, original, quantity = rows[0]
                    expected_refund = refund if state == "completed" else 0
                    expected_quantity = 1 if state == "completed" else 0
                    if row_refund != expected_refund or row_net != original - expected_refund or quantity != expected_quantity:
                        raise RuntimeError(f"{name}/{state}: incorrect refund propagation")
            print("PASS: compiled PostgreSQL incremental facts handle completed, cancelled and soft-deleted returns (6 assertions).")
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    main()
