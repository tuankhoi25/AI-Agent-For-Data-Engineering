"""Batch-aware dbt jobs shared by the Bakery component DAGs."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "analytics"
ARTIFACT_ROOT = PROJECT / "target/dagu"
sys.path.insert(0, str(PROJECT))

PHASES = {
    "staging": ["run", "--select", "path:models/staging"],
    "core": ["run", "--select", "path:models/core"],
    "snapshots": ["snapshot", "--select", "resource_type:snapshot"],
    "calendar": ["seed", "--select", "vietnam_holidays"],
    "dimensions-reference": ["run", "--selector", "dimensions_reference"],
    "dimensions-parties": ["run", "--selector", "dimensions_parties"],
    "dimensions-products": ["run", "--selector", "dimensions_products"],
    "facts-sales": ["run", "--selector", "facts_sales"],
    "facts-weather": ["run", "--selector", "facts_weather"],
    "marts-sales": ["run", "--selector", "marts_sales"],
    "marts-operations": ["run", "--selector", "marts_operations"],
    "data-tests": ["test"],
}
COMPONENT_SELECTORS = {
    "dimensions-reference": "dimensions_reference",
    "dimensions-parties": "dimensions_parties",
    "dimensions-products": "dimensions_products",
    "facts-sales": "facts_sales",
    "facts-weather": "facts_weather",
    "marts-sales": "marts_sales",
    "marts-operations": "marts_operations",
}
COMPONENT_BUILD_PHASES = {
    "source-core": ("staging", "core", "snapshots", "calendar"),
    **{component: (component,) for component in COMPONENT_SELECTORS},
}
COMPONENT_TEST_PHASES = {
    "source-core": "source-core-tests",
    **{component: f"{component}-tests" for component in COMPONENT_SELECTORS},
}
COMPONENT_PUBLISH_PHASES = {
    component: f"{component}-publish" for component in COMPONENT_BUILD_PHASES
}
COMPONENT_TEST_COMMANDS = {
    "source-core": ["test", "--select", "path:models/staging", "path:models/core",
                    "--indirect-selection", "cautious"],
    **{component: ["test", "--selector", selector, "--indirect-selection", "cautious"]
       for component, selector in COMPONENT_SELECTORS.items()},
}
FULL_PHASE_ORDER = ["preflight", *PHASES, "duckdb-smoke", "deep-audit", "publish-artifacts"]
PHASE_ORDER = ["preflight", *PHASES,
               *COMPONENT_TEST_PHASES.values(), *COMPONENT_PUBLISH_PHASES.values(),
               "duckdb-smoke", "deep-audit", "publish-artifacts"]
PHASE_DEPENDENCIES = {
    "preflight": set(),
    "staging": {"preflight"},
    "core": {"staging"},
    "snapshots": {"core"},
    "calendar": {"snapshots"},
    "dimensions-reference": {"calendar"},
    "dimensions-parties": {"snapshots"},
    "dimensions-products": {"dimensions-reference"},
    "facts-sales": {"dimensions-parties", "dimensions-products"},
    "facts-weather": {"dimensions-reference"},
    "marts-sales": {"facts-sales"},
    "marts-operations": {"dimensions-parties", "dimensions-products"},
    "data-tests": {"marts-sales", "marts-operations", "facts-weather"},
    "duckdb-smoke": {"data-tests"},
    "deep-audit": {"duckdb-smoke"},
    "publish-artifacts": {"deep-audit"},
}
for component, test_phase in COMPONENT_TEST_PHASES.items():
    build_phases = COMPONENT_BUILD_PHASES[component]
    PHASE_DEPENDENCIES[test_phase] = set(build_phases)
    PHASE_DEPENDENCIES[COMPONENT_PUBLISH_PHASES[component]] = {test_phase}


def descendants(phase):
    """Invalidate only this job and its actual dependants when retrying."""
    affected = {phase}
    while True:
        expanded = affected | {job for job, deps in PHASE_DEPENDENCIES.items() if deps & affected}
        if expanded == affected:
            return affected
        affected = expanded


@contextmanager
def phase_lock():
    (PROJECT / "target").mkdir(parents=True, exist_ok=True)
    with (PROJECT / "target/manual_pipeline.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another Bakery dbt command holds the local lock.") from None
        yield


def batch_identifier(value, now=None):
    if value == "auto":
        # The nightly window can cross midnight. 00:05 catalog publication
        # belongs to the same batch as the previous evening's 22:15 ingestion.
        local = now or datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        value = "daily-" + (local - timedelta(hours=6)).date().isoformat()
    if not value or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise RuntimeError("A safe Bakery batch ID is required; enqueue a scheduled DAG or pass BATCH_ID explicitly.")
    return value


def run_directory():
    run_id = batch_identifier(os.environ.get("BAKERY_BATCH_ID") or os.environ.get("DAG_RUN_ID")
                              or os.environ.get("DAGU_RUN_ID"))
    directory = ARTIFACT_ROOT / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def invoke_dbt(command, destination):
    from run_pipeline import dbt
    destination.mkdir(parents=True, exist_ok=True)
    results = PROJECT / "target/run_results.json"
    if results.exists():
        results.unlink()
    try:
        dbt(*command)
    finally:
        for name in ("manifest.json", "run_results.json", "catalog.json"):
            source = PROJECT / "target" / name
            if source.exists() and (name != "catalog.json" or command[:2] == ["docs", "generate"]):
                shutil.copy2(source, destination / name)
        log = PROJECT / "logs/dbt.log"
        if log.exists():
            shutil.copy2(log, destination / "dbt.log")


def write_json_atomic(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, default=str))
    temporary.replace(path)


def _selector_model_names(selector):
    """Return the model names owned by a dbt selector."""
    import yaml

    selectors = yaml.safe_load((PROJECT / "selectors.yml").read_text())["selectors"]
    selected = next(item for item in selectors if item["name"] == selector)["definition"]
    return {entry["value"] for entry in selected.get("union", [selected])}


def _component_owned_nodes(manifest, component):
    """Find a component's resources before adding its upstream closure."""
    nodes = manifest.get("nodes", {})
    if component == "source-core":
        return {
            key for key, node in nodes.items()
            if (node.get("resource_type") == "model" and
                (node.get("path", "").startswith("models/staging/") or
                 node.get("original_file_path", "").startswith("models/staging/") or
                 node.get("layer") == "staging"))
            or (node.get("resource_type") == "model" and
                (node.get("path", "").startswith("models/core/") or
                 node.get("original_file_path", "").startswith("models/core/") or
                 node.get("layer") == "core"))
            or node.get("resource_type") in {"snapshot", "seed"}
        }
    names = _selector_model_names(COMPONENT_SELECTORS[component])
    return {
        key for key, node in nodes.items()
        if node.get("resource_type") == "model" and node.get("name") in names
    }


def _component_artifact_closure(manifest, component):
    """Keep the selected models plus parents needed for catalog lineage."""
    nodes = manifest.get("nodes", {})
    sources = manifest.get("sources", {})
    selected = _component_owned_nodes(manifest, component)
    needed = set(selected)
    pending = list(selected)
    while pending:
        current = pending.pop()
        for parent in nodes.get(current, {}).get("depends_on", {}).get("nodes", []):
            if parent in nodes and parent not in needed:
                needed.add(parent)
                pending.append(parent)
    # Include tests attached to this component or one of its parents. Marmot's
    # dbt adapter uses these nodes for test metadata and run status.
    for key, node in nodes.items():
        if node.get("resource_type") == "test" and set(node.get("depends_on", {}).get("nodes", [])) & needed:
            needed.add(key)
    source_ids = set()
    for key in list(needed):
        source_ids.update(dep for dep in nodes.get(key, {}).get("depends_on", {}).get("nodes", []) if dep in sources)
    return needed, source_ids, selected


def _write_component_bundle(component, manifest, catalog, results, destination):
    """Write a self-contained dbt artifact bundle for one component."""
    needed, source_ids, selected = _component_artifact_closure(manifest, component)
    filtered_manifest = deepcopy(manifest)
    filtered_manifest["nodes"] = {key: node for key, node in manifest.get("nodes", {}).items() if key in needed}
    filtered_manifest["sources"] = {key: node for key, node in manifest.get("sources", {}).items() if key in source_ids}
    filtered_catalog = deepcopy(catalog)
    filtered_catalog["nodes"] = {key: node for key, node in catalog.get("nodes", {}).items() if key in needed}
    filtered_catalog["sources"] = {key: node for key, node in catalog.get("sources", {}).items() if key in source_ids}
    destination.mkdir(parents=True, exist_ok=True)
    write_json_atomic(destination / "manifest.json", filtered_manifest)
    write_json_atomic(destination / "catalog.json", filtered_catalog)
    by_id = {}
    for result in results:
        by_id[result["unique_id"]] = result
    filtered_results = [result for key, result in by_id.items() if key in needed]
    if not selected.issubset({result["unique_id"] for result in filtered_results}):
        missing = sorted(selected - {result["unique_id"] for result in filtered_results})
        raise RuntimeError(f"Missing dbt results for {component}: {', '.join(missing)}")
    if any(result.get("status") not in {"success", "pass", "warn"} for result in filtered_results):
        raise RuntimeError(f"Cannot publish failed dbt resources for {component}")
    template = {"metadata": manifest.get("metadata", {}), "results": filtered_results,
                "elapsed_time": sum(result.get("execution_time", 0) for result in filtered_results)}
    write_json_atomic(destination / "run_results.json", template)
    write_json_atomic(destination / "component.json", {
        "component": component,
        "owned_unique_ids": sorted(selected),
        "resources": len(filtered_results),
    })


def publish_component(directory, component, attempts, destination):
    """Create and immediately ingest this component's catalog bundle."""
    build_phases = COMPONENT_BUILD_PHASES[component]
    required = set(build_phases) | {COMPONENT_TEST_PHASES[component]}
    if not required.issubset(attempts):
        raise RuntimeError(f"Component {component} is not ready for publication")
    raw = destination / "raw"
    invoke_dbt(["docs", "generate", "--no-compile"], raw)
    manifest = json.loads((raw / "manifest.json").read_text())
    catalog = json.loads((raw / "catalog.json").read_text())
    results = []
    for phase in (*build_phases, COMPONENT_TEST_PHASES[component]):
        artifact = directory / attempts[phase]
        result_path = artifact / "run_results.json"
        if result_path.exists():
            results.extend(json.loads(result_path.read_text()).get("results", []))
    bundle = destination / "catalog"
    _write_component_bundle(component, manifest, catalog, results, bundle)
    from catalog import sync_component
    result = sync_component(component, bundle)
    write_json_atomic(destination / "publication.json", result)
    print(json.dumps({"component": component, "published": True, **result}))


def publish(run_dir, attempts, catalog):
    invoke_dbt(["docs", "generate", "--no-compile"], catalog)
    combined, template, elapsed = {}, None, 0
    for phase in PHASES:
        source = run_dir / attempts[phase] / "run_results.json"
        template = json.loads(source.read_text())
        elapsed += template.get("elapsed_time", 0)
        for item in template["results"]:
            combined[item["unique_id"]] = item
    manifest = json.loads((catalog / "manifest.json").read_text())
    expected = {key for key, node in manifest["nodes"].items()
                if node["resource_type"] in {"model", "snapshot", "test", "seed"}}
    if set(combined) != expected:
        raise RuntimeError("Missing dbt resources in published aggregate results")
    if any(row["status"] not in {"success", "pass", "warn"} for row in combined.values()):
        raise RuntimeError("Cannot publish failed/skipped dbt resources")
    template.update(results=list(combined.values()), elapsed_time=elapsed)
    write_json_atomic(catalog / "run_results.json", template)
    pointer = {"dag_run_id": run_dir.name, "catalog_path": str(catalog.relative_to(ARTIFACT_ROOT)),
               "published_at": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(), "resources": len(combined)}
    write_json_atomic(ARTIFACT_ROOT / "latest_success.json", pointer)
    print(json.dumps(pointer))


def execute(phase):
    from run_pipeline import check_manifest, check_live_source, check_duckdb_reporting
    os.environ["PGOPTIONS"] = "-c duckdb.force_execution=off -c timezone=Asia/Ho_Chi_Minh"
    directory = run_directory()
    state_path = directory / "completed_phases.json"
    with phase_lock():
        attempts = json.loads(state_path.read_text()) if state_path.exists() else {}
        missing = PHASE_DEPENDENCIES[phase] - attempts.keys()
        if missing:
            raise RuntimeError("Missing successful jobs in this batch: " + ", ".join(sorted(missing)))
        # All children share the parent's batch directory. A failed retry must
        # invalidate dependent gates without losing successful sibling jobs.
        for downstream in descendants(phase):
            attempts.pop(downstream, None)
        write_json_atomic(state_path, attempts)
        phase_root = directory / phase
        phase_root.mkdir(exist_ok=True)
        destination = phase_root / f"attempt-{len(list(phase_root.glob('attempt-*'))) + 1}"
        destination.mkdir()
        write_json_atomic(destination / "execution.json", {
            "batch_id": directory.name,
            "dag_run_id": os.environ.get("DAG_RUN_ID") or os.environ.get("DAGU_RUN_ID"),
            "phase": phase,
        })
        if phase == "preflight":
            invoke_dbt(["parse", "--no-partial-parse"], destination)
            check_live_source(check_manifest())
        elif phase in PHASES:
            command = list(PHASES[phase])
            if command[0] == "build":
                command += ["--indirect-selection", "cautious", "--fail-fast"]
            elif command[0] == "run":
                command += ["--fail-fast"]
            invoke_dbt(command, destination)
        elif phase in COMPONENT_TEST_PHASES.values():
            component = next(name for name, test_phase in COMPONENT_TEST_PHASES.items() if test_phase == phase)
            if not set(COMPONENT_BUILD_PHASES[component]).issubset(attempts):
                raise RuntimeError(f"Component {component} build has not completed")
            invoke_dbt(COMPONENT_TEST_COMMANDS[component], destination)
        elif phase in COMPONENT_PUBLISH_PHASES.values():
            component = next(name for name, publish_phase in COMPONENT_PUBLISH_PHASES.items() if publish_phase == phase)
            publish_component(directory, component, attempts, destination)
        elif phase == "duckdb-smoke":
            check_duckdb_reporting()
        elif phase == "deep-audit":
            enabled = os.environ.get("DEEP_AUDIT", "auto").lower()
            if enabled not in {"auto", "true", "false"}:
                raise ValueError("DEEP_AUDIT must be auto, true or false")
            due = enabled == "true" or (enabled == "auto" and datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).weekday() == 6)
            if due:
                subprocess.run([sys.executable, str(PROJECT / "validate_pipeline.py"), "--output",
                                str(destination / "validation.json")], cwd=ROOT, check=True, timeout=3600)
            else:
                print("Deep audit not due; quality tests and DuckDB smoke still apply.")
        elif phase == "publish-artifacts":
            required = set(PHASES) | {"preflight", "duckdb-smoke", "deep-audit"}
            if not required.issubset(attempts):
                raise RuntimeError("Quality gates have not all completed for this Dagu run")
            publish(directory, attempts, destination / "catalog")
        else:
            raise ValueError("Unknown phase")
        attempts[phase] = str(destination.relative_to(directory))
        write_json_atomic(state_path, attempts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=PHASE_ORDER)
    execute(parser.parse_args().phase)
