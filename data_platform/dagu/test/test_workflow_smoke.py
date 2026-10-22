"""Opt-in real Dagu execution with synthetic dbt artifacts and no DB access.

DAGU_TEST_BINARY=/path/to/dagu python -m unittest discover -s data_platform/dagu/test
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import yaml

DAGU_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DAGU_DIRECTORY))
import pipeline


@unittest.skipUnless(os.environ.get("DAGU_TEST_BINARY"), "Set DAGU_TEST_BINARY for native workflow smoke")
class NativeWorkflowTests(unittest.TestCase):
    def test_batch_identity_publication_and_failed_branch(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            dags = directory / "dags"
            dags.mkdir()
            project = directory / "analytics"
            project.mkdir()
            # Use the declared SQL resources, not existing platform data/artifacts.
            nodes = {}
            for layer in ("staging", "core", "mart"):
                for path in (pipeline.PROJECT / "models" / layer).glob("*.sql"):
                    key = "model.analytics." + path.stem
                    nodes[key] = {"resource_type": "model", "name": path.stem,
                                  "schema": "analytics_" + layer, "layer": layer}
            for name in ("dim_allergens", "dim_branches", "dim_customers", "dim_employees",
                         "dim_inventory_lots", "dim_product_categories", "dim_products", "dim_promotions",
                         "dim_recipes", "dim_stock_items", "dim_suppliers", "dim_units_of_measure"):
                nodes["snapshot.analytics.snap_" + name] = {"resource_type": "snapshot", "schema": "analytics_mart"}
            nodes["seed.analytics.vietnam_holidays"] = {"resource_type": "seed"}
            nodes["test.analytics.synthetic_quality_gate"] = {"resource_type": "test"}
            (directory / "manifest.json").write_text(json.dumps({"nodes": nodes}))
            selectors = yaml.safe_load((pipeline.PROJECT / "selectors.yml").read_text())
            (directory / "selectors.yml").write_text(yaml.safe_dump(selectors))
            helper = directory / "synthetic_job.py"
            helper.write_text('''
import json, os, sys
from pathlib import Path
import yaml
sys.path.insert(0, sys.argv[1])
import pipeline, run_pipeline
from datetime import datetime
from zoneinfo import ZoneInfo
resolve_batch = pipeline.batch_identifier
pipeline.batch_identifier = lambda value: resolve_batch(value, datetime(2026, 10, 22, 23, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))
base = Path(__file__).parent
pipeline.PROJECT = base / "analytics"
pipeline.ARTIFACT_ROOT = pipeline.PROJECT / "target/dagu"
manifest = json.loads((base / "manifest.json").read_text())
selectors = {s["name"]: s["definition"] for s in yaml.safe_load((base / "selectors.yml").read_text())["selectors"]}
phase = sys.argv[2]
def fake_dbt(command, destination):
    destination.mkdir(parents=True, exist_ok=True)
    if phase == os.environ.get("BAKERY_TEST_FAIL_PHASE"):
        raise RuntimeError("Synthetic failure")
    names = None
    if "--selector" in command:
        spec = selectors[command[command.index("--selector") + 1]]
        names = {entry["value"] for entry in spec.get("union", [spec])}
    result = []
    for key, node in manifest["nodes"].items():
        kind = node["resource_type"]
        include = ((command[0] in {"build", "run"} and kind == "model" and
                    ((names is not None and node["name"] in names) or
                     (names is None and "path:models/" + node["layer"] in command))) or
                   (command[0] == "snapshot" and kind == "snapshot") or
                   (command[0] == "seed" and kind == "seed") or
                   (command[0] == "test" and kind == "test"))
        if include:
            result.append({"unique_id": key, "status": "pass" if kind == "test" else "success"})
    (destination / "manifest.json").write_text(json.dumps(manifest))
    (destination / "run_results.json").write_text(json.dumps({"results": result, "elapsed_time": 0}))
    (destination / "catalog.json").write_text("{}")
pipeline.invoke_dbt = fake_dbt
pipeline.publish_component = lambda directory, component, attempts, destination: None
run_pipeline.check_manifest = lambda: []
run_pipeline.check_live_source = lambda sources: None
run_pipeline.check_duckdb_reporting = lambda: None
pipeline.execute(phase)
''')
            config = directory / "config.yaml"
            config.write_text(yaml.safe_dump({"auth": {"mode": "none"},
                                             "paths": {"dags_dir": str(dags)},
                                             "tz": "Asia/Ho_Chi_Minh"}))
            env = dict(os.environ, DAGU_HOME=str(directory / "home"), DAGU_SKIP_EXAMPLES="true")
            for source in (DAGU_DIRECTORY / "dags").glob("*.yaml"):
                spec = yaml.safe_load(source.read_text())
                if source.stem == "weather-daily":
                    continue
                spec.pop("schedule", None)
                spec["working_dir"] = str(directory)
                spec["defaults"] = {"retry_policy": {"limit": 0, "interval_sec": 1}}
                spec.setdefault("env", {})["BAKERY_TEST_FAIL_PHASE"] = ""
                for step in spec["steps"]:
                    if "run" in step:
                        if step["run"].endswith("catalog.py dagu"):
                            step["run"] = shlex.join([sys.executable, "-c", "pass"])
                        else:
                            phase = step["run"].rsplit(" ", 1)[-1]
                            step["run"] = shlex.join([sys.executable, str(helper), str(DAGU_DIRECTORY), phase])
                (dags / source.name).write_text(yaml.safe_dump(spec, sort_keys=False))
            # Independent cron DAGs have no parent run ID in common. Their
            # default BATCH_ID=auto must still produce one complete batch.
            for path in dags.glob("*.yaml"):
                spec = yaml.safe_load(path.read_text())
                spec["env"]["BAKERY_TEST_FAIL_PHASE"] = ""
                path.write_text(yaml.safe_dump(spec, sort_keys=False))
            scheduled = ["source-core", "dimensions-reference", "dimensions-parties", "dimensions-products",
                         "facts-sales", "facts-weather", "marts-sales", "marts-operations"]
            for index, name in enumerate(scheduled):
                command = [os.environ["DAGU_TEST_BINARY"], "start", "--config", str(config),
                           "--run-id", f"scheduled-{index}"]
                command += [str(dags / f"{name}.yaml")]
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-4000:])
            state = json.loads((project / "target/dagu/runs/daily-2026-10-22/completed_phases.json").read_text())
            for component in pipeline.COMPONENT_BUILD_PHASES:
                self.assertIn(pipeline.COMPONENT_PUBLISH_PHASES[component], state)


if __name__ == "__main__":
    unittest.main()
