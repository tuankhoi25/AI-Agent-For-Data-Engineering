from contextlib import nullcontext
from datetime import datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline


class ArtifactSafetyTests(unittest.TestCase):
    def test_component_tasks_have_run_test_publish_order(self):
        for component in pipeline.COMPONENT_BUILD_PHASES:
            test_phase = pipeline.COMPONENT_TEST_PHASES[component]
            publish_phase = pipeline.COMPONENT_PUBLISH_PHASES[component]
            self.assertEqual(pipeline.PHASE_DEPENDENCIES[test_phase],
                             set(pipeline.COMPONENT_BUILD_PHASES[component]))
            self.assertEqual(pipeline.PHASE_DEPENDENCIES[publish_phase], {test_phase})

    def test_component_bundle_filters_to_owned_models_and_upstream_closure(self):
        manifest = {
            "metadata": {"dbt_version": "1.0"},
            "nodes": {
                "model.analytics.dim_products": {
                    "resource_type": "model", "name": "dim_products", "path": "models/mart/dim_products.sql",
                    "schema": "analytics_mart", "depends_on": {"nodes": ["model.analytics.dim_product_categories"]},
                },
                "model.analytics.dim_product_categories": {
                    "resource_type": "model", "name": "dim_product_categories", "path": "models/mart/x.sql",
                    "schema": "analytics_mart", "depends_on": {"nodes": []},
                },
                "model.analytics.mart_daily_sales": {
                    "resource_type": "model", "name": "mart_daily_sales", "path": "models/mart/y.sql",
                    "schema": "analytics_mart", "depends_on": {"nodes": []},
                },
                "test.analytics.products": {
                    "resource_type": "test", "depends_on": {"nodes": ["model.analytics.dim_products"]},
                },
            },
            "sources": {},
        }
        catalog = {"nodes": {key: {"columns": {}} for key in manifest["nodes"]}, "sources": {}}
        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "bundle"
            with patch.object(pipeline, "_selector_model_names", return_value={"dim_products"}):
                pipeline._write_component_bundle(
                    "dimensions-products", manifest, catalog,
                    [{"unique_id": key, "status": "success"} for key in manifest["nodes"]], destination)
            written = json.loads((destination / "manifest.json").read_text())
            self.assertIn("model.analytics.dim_products", written["nodes"])
            self.assertIn("model.analytics.dim_product_categories", written["nodes"])
            self.assertNotIn("model.analytics.mart_daily_sales", written["nodes"])
            self.assertIn("test.analytics.products", written["nodes"])

    def test_unsafe_run_id_rejected(self):
        with patch.dict("os.environ", {"DAG_RUN_ID": "../other", "DAGU_RUN_ID": ""}):
            with self.assertRaises(RuntimeError):
                pipeline.run_directory()

    def test_failed_upstream_retry_invalidates_downstream_success(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            state = directory / "completed_phases.json"
            state.write_text(json.dumps({phase: "old-attempt" for phase in pipeline.PHASE_ORDER}))
            with patch("pipeline.run_directory", return_value=directory), patch("pipeline.phase_lock", return_value=nullcontext()), patch("pipeline.invoke_dbt", side_effect=RuntimeError("dbt failed")):
                with self.assertRaises(RuntimeError):
                    pipeline.execute("core")
            self.assertEqual(set(json.loads(state.read_text())), {"preflight", "staging"})

    def test_child_uses_parent_batch_instead_of_its_own_run_id(self):
        with TemporaryDirectory() as temporary, patch("pipeline.ARTIFACT_ROOT", Path(temporary)):
            with patch.dict("os.environ", {"BAKERY_BATCH_ID": "parent-batch", "DAG_RUN_ID": "child-run"}):
                self.assertEqual(pipeline.run_directory().name, "parent-batch")

    def test_nightly_batch_stays_the_same_across_midnight(self):
        tz = ZoneInfo("Asia/Ho_Chi_Minh")
        evening = datetime(2026, 10, 22, 22, 15, tzinfo=tz)
        catalog = datetime(2026, 10, 23, 0, 5, tzinfo=tz)
        next_evening = datetime(2026, 10, 23, 22, 15, tzinfo=tz)
        self.assertEqual(pipeline.batch_identifier("auto", evening), "daily-2026-10-22")
        self.assertEqual(pipeline.batch_identifier("auto", catalog), "daily-2026-10-22")
        self.assertEqual(pipeline.batch_identifier("auto", next_evening), "daily-2026-10-23")

    def test_catalog_cannot_silently_ingest_previous_batch(self):
        import catalog
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "latest_success.json").write_text(json.dumps({"dag_run_id": "old-batch"}))
            with patch("catalog.ARTIFACT_ROOT", directory), patch.dict("os.environ", {"BAKERY_BATCH_ID": "new-batch"}), patch("catalog.MarmotClient") as client:
                with self.assertRaisesRegex(RuntimeError, "older catalog"):
                    catalog.sync_dbt()
                client.assert_not_called()

    def test_catalog_rejects_same_batch_after_failed_upstream_retry(self):
        import catalog
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            batch = directory / "runs/daily-2026-10-22"
            batch.mkdir(parents=True)
            (directory / "latest_success.json").write_text(json.dumps({
                "dag_run_id": batch.name, "catalog_path": f"runs/{batch.name}/publish-artifacts/attempt-1/catalog"}))
            (batch / "completed_phases.json").write_text(json.dumps({"preflight": "attempt"}))
            with patch("catalog.ARTIFACT_ROOT", directory), patch.dict("os.environ", {"BAKERY_BATCH_ID": batch.name}), patch("catalog.MarmotClient") as client:
                with self.assertRaisesRegex(RuntimeError, "invalidated"):
                    catalog.sync_dbt()
                client.assert_not_called()

    def test_failed_party_retry_preserves_unrelated_product_and_weather_jobs(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            state = directory / "completed_phases.json"
            state.write_text(json.dumps({phase: "old-attempt" for phase in pipeline.PHASE_ORDER}))
            with patch("pipeline.run_directory", return_value=directory), patch("pipeline.phase_lock", return_value=nullcontext()), patch("pipeline.invoke_dbt", side_effect=RuntimeError("dbt failed")):
                with self.assertRaises(RuntimeError):
                    pipeline.execute("dimensions-parties")
            remaining = json.loads(state.read_text())
            self.assertIn("dimensions-products", remaining)
            self.assertIn("facts-weather", remaining)
            self.assertNotIn("facts-sales", remaining)
            self.assertNotIn("marts-operations", remaining)
            self.assertNotIn("publish-artifacts", remaining)

    def test_child_without_same_batch_prerequisites_cannot_write(self):
        with TemporaryDirectory() as temporary:
            with patch("pipeline.run_directory", return_value=Path(temporary)), patch("pipeline.phase_lock", return_value=nullcontext()), patch("pipeline.invoke_dbt") as invoke:
                with self.assertRaisesRegex(RuntimeError, "Missing successful jobs"):
                    pipeline.execute("facts-sales")
                invoke.assert_not_called()

    def test_missing_quality_gates_cannot_publish(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "completed_phases.json").write_text(json.dumps({"preflight": "old"}))
            with patch("pipeline.run_directory", return_value=directory), patch("pipeline.phase_lock", return_value=nullcontext()), patch("pipeline.publish") as publish:
                with self.assertRaises(RuntimeError):
                    pipeline.execute("publish-artifacts")
                publish.assert_not_called()

    def test_successful_child_records_actual_execution_and_parent_batch(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "parent-batch"
            directory.mkdir()
            (directory / "completed_phases.json").write_text(json.dumps({"dimensions-reference": "ref"}))
            with patch("pipeline.run_directory", return_value=directory), patch("pipeline.phase_lock", return_value=nullcontext()), patch("pipeline.invoke_dbt"), patch.dict("os.environ", {"DAG_RUN_ID": "child-run"}):
                pipeline.execute("facts-weather")
            execution = json.loads((directory / "facts-weather/attempt-1/execution.json").read_text())
            self.assertEqual(execution["batch_id"], "parent-batch")
            self.assertEqual(execution["dag_run_id"], "child-run")


class WorkflowContractTests(unittest.TestCase):
    def test_each_active_dag_ends_with_metadata_sync(self):
        dags = pipeline.ROOT / "data_platform/dagu/dags"
        self.assertFalse((dags / "validation-publish.yaml").exists())
        self.assertFalse((dags / "catalog-sync.yaml").exists())
        for path in dags.glob("*.yaml"):
            steps = yaml.safe_load(path.read_text())["steps"]
            self.assertEqual(steps[-1]["id"], "metadata", path.name)
            self.assertEqual(steps[-1]["run"], "python data_platform/dagu/catalog.py dagu")

    def test_mart_selectors_have_exactly_one_owner_per_model(self):
        selectors = yaml.safe_load((pipeline.PROJECT / "selectors.yml").read_text())["selectors"]
        names = []
        for selector in selectors:
            definition = selector["definition"]
            for entry in definition.get("union", [definition]):
                self.assertEqual(entry["method"], "fqn")
                names.append(entry["value"])
        expected = {path.stem for path in (pipeline.PROJECT / "models/mart").glob("*.sql")}
        self.assertEqual(set(names), expected)
        self.assertEqual(len(names), len(expected))

if __name__ == "__main__":
    unittest.main()
