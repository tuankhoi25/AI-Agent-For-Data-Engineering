"""Catalog publication helpers used by component DAGs and manual syncs."""
import argparse
import json
import os
from pathlib import Path

from marmot import MarmotClient
from pipeline import ARTIFACT_ROOT, FULL_PHASE_ORDER, batch_identifier, phase_lock


def sync_dbt():
    pointer = json.loads((ARTIFACT_ROOT / "latest_success.json").read_text())
    requested = os.environ.get("BAKERY_BATCH_ID", "latest")
    if requested != "latest" and pointer["dag_run_id"] != batch_identifier(requested):
        raise RuntimeError("This nightly batch has not published successfully; refusing to sync an older catalog.")
    if requested != "latest":
        state_path = ARTIFACT_ROOT / "runs" / pointer["dag_run_id"] / "completed_phases.json"
        state = json.loads(state_path.read_text())
        expected = f"runs/{pointer['dag_run_id']}/{state.get('publish-artifacts', '')}/catalog"
        if not set(FULL_PHASE_ORDER).issubset(state) or pointer["catalog_path"] != expected:
            raise RuntimeError("Batch gates were invalidated; wait for validation/publication before catalog sync.")
    relative = Path(pointer["catalog_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe catalog artifact path")
    catalog = ARTIFACT_ROOT / relative
    artifacts = {name: json.loads((catalog / f"{name}.json").read_text())
                 for name in ("manifest", "catalog", "run_results")}
    manifest = artifacts["manifest"]
    if any(n["schema"] not in {"analytics_staging", "analytics_core", "analytics_mart"}
           for n in manifest["nodes"].values() if n["resource_type"] in {"model", "snapshot"}):
        raise RuntimeError("Unexpected target schema")
    client = MarmotClient()
    try:
        client.wait_for_plugins()
        edges = client.snapshot_assets(manifest, artifacts["catalog"])
        schedule = client.upsert({
            "name": "bakery-dbt-artifacts", "plugin_id": "dbt",
            "cron_expression": "0 0 * * *", "enabled": False,
            "config": {"target_path": "/data/dagu-artifacts/" + relative.as_posix(),
                       "project_name": "analytics", "environment": "local",
                       "include_manifest": True, "include_catalog": True,
                       "include_run_results": True, "discover_models": True,
                       "discover_sources": True, "discover_tests": True,
                       "tags": ["bakery", "dbt", "dagu-managed"]}})
        result = client.trigger_and_wait(schedule)
        if edges:
            linked = client.request("POST", "lineage/batch", json=edges)
            if len(linked) != len(edges) or any(e.get("status") not in {"created", "duplicate", "existing"} for e in linked):
                raise RuntimeError("Snapshot lineage incomplete")
        result["verification"] = client.verify_catalog(manifest)
        return result
    finally:
        client.close()


def sync_component(component, catalog):
    """Ingest one component bundle immediately after its dbt tests pass.

    The bundle is intentionally filtered to the component and its upstream
    closure. It is published under its own idempotent Marmot schedule so a
    retry updates the same assets instead of creating a second catalog graph.
    """
    catalog = Path(catalog).resolve()
    root = ARTIFACT_ROOT.resolve()
    try:
        relative = catalog.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("Component catalog must live under the artifact root") from exc
    artifacts = {name: json.loads((catalog / f"{name}.json").read_text())
                 for name in ("manifest", "catalog", "run_results")}
    manifest = artifacts["manifest"]
    component_info = json.loads((catalog / "component.json").read_text())
    if component_info.get("component") != component:
        raise RuntimeError("Component artifact identity mismatch")
    owned = set(component_info.get("owned_unique_ids", []))
    models = {key for key, node in manifest.get("nodes", {}).items()
              if node.get("resource_type") == "model"}
    if not owned or not owned.issubset(models | {
        key for key, node in manifest.get("nodes", {}).items()
        if node.get("resource_type") in {"snapshot", "seed"}
    }):
        raise RuntimeError("Component artifact has no valid owned dbt resources")
    if any(node.get("schema") not in {"analytics_staging", "analytics_core", "analytics_mart"}
           for node in manifest.get("nodes", {}).values()
           if node.get("resource_type") in {"model", "snapshot"}):
        raise RuntimeError("Unexpected target schema in component artifact")
    if any(result.get("status") not in {"success", "pass", "warn"}
           for result in artifacts["run_results"].get("results", [])):
        raise RuntimeError("Cannot ingest a component with failed dbt results")

    client = MarmotClient()
    try:
        client.wait_for_plugins()
        edges = client.snapshot_assets(manifest, artifacts["catalog"])
        schedule = client.upsert({
            "name": "bakery-dbt-component-" + component,
            "plugin_id": "dbt",
            "cron_expression": "0 0 * * *",
            "enabled": False,
            "config": {
                "target_path": "/data/dagu-artifacts/" + relative.as_posix(),
                "project_name": "analytics",
                "environment": "local",
                "include_manifest": True,
                "include_catalog": True,
                "include_run_results": True,
                "discover_models": True,
                "discover_sources": True,
                "discover_tests": True,
                "tags": ["bakery", "dbt", "dagu-managed", "component:" + component],
            },
        })
        result = client.trigger_and_wait(schedule)
        if edges:
            linked = client.request("POST", "lineage/batch", json=edges)
            if len(linked) != len(edges) or any(
                    edge.get("status") not in {"created", "duplicate", "existing"} for edge in linked):
                raise RuntimeError("Component snapshot lineage incomplete")
        result["verification"] = client.verify_catalog(manifest)
        result["component"] = component
        result["artifact_path"] = relative.as_posix()
        return result
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["dbt", "dagu"])
    args = parser.parse_args()
    with phase_lock():
        if args.kind == "dbt":
            result = sync_dbt()
        else:
            from dagu_sync import sync
            result = sync()
    print(json.dumps(result, indent=2))
