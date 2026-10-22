"""Regression checks with in-memory fixtures, without Docker or PostgreSQL.

DuckDB is only a local SQL test harness here. Live dbt-postgres verification
must still be performed after the platform starts.
"""

from pathlib import Path
import re
from types import SimpleNamespace
import unittest

import duckdb
from jinja2 import Environment, StrictUndefined


PROJECT = Path(__file__).resolve().parents[1]
MACROS = (PROJECT / "macros/staging_incremental.sql").read_text()


class FixtureRelation:
    schema = "main"
    identifier = "target_rows"

    def __str__(self):
        return self.identifier


def render_macro(name, args, *, incremental, keys=("product_id",)):
    source = re.search(
        r"{% macro " + name + r"\([^%]*%}.*?{% endmacro %}",
        MACROS, re.DOTALL,
    ).group()
    env = Environment(undefined=StrictUndefined)
    env.globals.update(
        ref=lambda name: name,
        source=lambda schema, table: "source_rows",
        config=lambda **kwargs: "",
        is_incremental=lambda: incremental,
        var=lambda key, default=None: default,
        model_business_keys=lambda name: list(keys),
        model=SimpleNamespace(name="stg_products"),
        invocation_id="fixture-batch",
        this=FixtureRelation(),
    )
    # DuckDB has the same sequence operation, without PostgreSQL's regclass cast.
    return str(getattr(env.from_string(source).module, name)(*args)).replace("::regclass", "")


class StagingContract(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect()
        self.db.execute("""
            create table source_rows (
                product_id bigint, _last_updated_at timestamptz,
                _is_deleted boolean
            );
            insert into source_rows values
                (1, '2026-10-20 12:00:00+00', false),
                (2, '2026-10-20 13:00:00+00', false)
        """)
        sql = render_macro("source_incremental", ("bakery", "products"), incremental=False)
        self.db.execute("create table target_rows as " + sql)

    def tearDown(self):
        self.db.close()

    def load(self):
        sql = render_macro("source_incremental", ("bakery", "products"), incremental=True)
        self.db.execute("insert into target_rows " + sql)

    def test_unchanged_rerun_appends_nothing(self):
        self.load()
        self.load()
        self.assertEqual(self.db.sql("select count(*) from target_rows").fetchone()[0], 2)

    def test_late_commit_and_equal_watermark_are_loaded_once(self):
        # Both rows become visible after the previous extraction. Their source
        # timestamps are respectively older than and equal to the high watermark.
        self.db.execute("""
            insert into source_rows values
                (3, '2026-10-20 12:30:00+00', false),
                (4, '2026-10-20 13:00:00+00', false)
        """)
        self.load()
        self.load()
        self.assertEqual(self.db.sql("select count(*) from target_rows").fetchone()[0], 4)

    def test_soft_delete_and_restore_preserve_versions(self):
        self.db.execute("update source_rows set _last_updated_at='2026-10-21 12:00:00+00', _is_deleted=true where product_id=1")
        self.load()
        self.db.execute("update source_rows set _last_updated_at='2026-10-22 12:00:00+00', _is_deleted=false where product_id=1")
        self.load()
        self.load()
        flags = self.db.sql("select _is_deleted from target_rows where product_id=1 order by _source_last_updated_at").fetchall()
        self.assertEqual(flags, [(False,), (True,), (False,)])

    def test_composite_business_key_is_preserved(self):
        self.db.execute("alter table source_rows add column allergen_id bigint default 10")
        self.db.execute("alter table target_rows add column allergen_id bigint default 10")
        self.db.execute("insert into source_rows values (1, '2026-10-20 12:00:00+00', false, 20)")
        sql = render_macro("source_incremental", ("bakery", "products"), incremental=True, keys=("product_id", "allergen_id"))
        # Added fixture column has a different physical position in the target.
        self.db.execute("insert into target_rows by name " + sql)
        self.db.execute("insert into target_rows by name " + sql)
        self.assertEqual(self.db.sql("select count(*) from target_rows where product_id=1").fetchone()[0], 2)


class DimensionContract(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect()
        self.db.execute("""
            create sequence target_rows_sk_seq;
            create table snap_dim_products (
                product_id bigint, dbt_scd_id varchar,
                dbt_valid_from timestamptz, dbt_valid_to timestamptz
            );
            insert into snap_dim_products values
                (1, 'v1', '2026-10-20 12:00:00+00', null)
        """)
        sql = self.rows(False)
        self.db.execute("""
            create table target_rows as select product_id, product_sk,
                dbt_scd_id as _dimension_version_id,
                _effective_valid_from as _valid_from,
                dbt_valid_from as _observed_from, dbt_valid_to as _valid_to
            from (""" + sql + ")")

    def tearDown(self):
        self.db.close()

    def rows(self, incremental):
        return render_macro("scd2_dimension_rows", ("snap_dim_products", "product_sk", "product_id"), incremental=incremental)

    def test_backfill_event_resolves_initial_key(self):
        row = self.db.sql("""
            select product_sk, _observed_from::date::text from target_rows
            where '2026-10-01'::timestamptz >= _valid_from
              and '2026-10-01'::timestamptz < coalesce(_valid_to, 'infinity'::timestamptz)
        """).fetchone()
        self.assertEqual(row, (1, "2026-10-20"))

    def test_close_and_open_preserves_existing_sk(self):
        self.db.execute("""
            update snap_dim_products set dbt_valid_to='2026-10-21 12:00:00+00' where dbt_scd_id='v1';
            insert into snap_dim_products values (1, 'v2', '2026-10-21 12:00:00+00', null)
        """)
        self.db.execute("""
            merge into target_rows as t using (""" + self.rows(True) + """) as s
            on t._dimension_version_id = s.dbt_scd_id
            when matched then update set _valid_to = s.dbt_valid_to
            when not matched then insert values (
                s.product_id, s.product_sk, s.dbt_scd_id,
                s._effective_valid_from, s.dbt_valid_from, s.dbt_valid_to
            )
        """)
        self.assertEqual(self.db.sql("select product_sk from target_rows order by product_sk").fetchall(), [(1,), (2,)])
        self.assertEqual(self.db.sql("select count(*) from (" + self.rows(True) + ")").fetchone()[0], 0)
        self.assertEqual(self.db.sql("select product_sk from target_rows where _valid_to is null").fetchone()[0], 2)


class SCDQualityChecks(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect()
        self.env = Environment(undefined=StrictUndefined)
        self.env.globals.update(ref=lambda name: "quality_rows", config=lambda **kwargs: "")
        path = PROJECT / "test/test_scd2_dimension_intervals.sql"
        dimensions = self.env.from_string(path.read_text()).module.dimensions
        keys = ", ".join(f"{key} bigint default 1" for _, key in dimensions)
        self.db.execute(f"""
            create table quality_rows (
                {keys}, _valid_from timestamptz, _valid_to timestamptz,
                _observed_from timestamptz, _is_current boolean
            )
        """)

    def tearDown(self):
        self.db.close()

    def violations(self, name):
        sql = self.env.from_string((PROJECT / "test" / name).read_text()).render()
        return self.db.sql(sql).fetchall()

    def test_missing_current_version_is_detected(self):
        self.db.execute("""
            insert into quality_rows (_valid_from, _valid_to, _observed_from, _is_current)
            values ('-infinity', '2026-10-21 12:00:00+00', '2026-10-20 12:00:00+00', false)
        """)
        self.assertEqual(len(self.violations("test_scd2_dimensions_have_one_current_version.sql")), 12)

    def test_overlapping_versions_are_detected(self):
        self.db.execute("""
            insert into quality_rows (_valid_from, _valid_to, _observed_from, _is_current)
            values ('-infinity', '2026-10-22 12:00:00+00', '2026-10-20 12:00:00+00', false),
                   ('2026-10-21 12:00:00+00', null, '2026-10-21 12:00:00+00', true)
        """)
        self.assertEqual(len(self.violations("test_scd2_dimension_intervals.sql")), 12)


if __name__ == "__main__":
    unittest.main()
