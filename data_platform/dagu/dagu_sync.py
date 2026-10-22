"""Method A: read Dagu's REST API, publish only allowlisted metadata to Marmot.

No raw commands, parameters, environment, logs or credentials are exported.
Deleted definitions are retired (not hard-deleted); only our graph edges prune.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import quote
import uuid

import httpx
import yaml

from marmot import MarmotClient

OWNER = "bakery-dagu-sync-v1"
INSTANCE = "bakery-local"
STATE = Path("/var/lib/dagu/marmot-sync-state.json")


def identity(kind, name):
    return f"mrn://{kind.lower()}/dagu/{name.lower()}"


def history(mrn, name, run_id, status, started, finished, observed):
    """Replay stable run events idempotently; never invent execution timestamps."""
    events = []
    key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{INSTANCE}/{name}/{run_id}"))
    base = {"asset_mrn": mrn, "job_namespace": "dagu:" + INSTANCE,
            "job_name": name, "run_id": key,
            "run_facets": {"dagu": {"dag_run_id": run_id, "status": status, "observed_at": observed}}}
    if started and not started.startswith("0001-"):
        events.append(dict(base, event_type="START", event_time=started))
    terminal = {"succeeded": "COMPLETE", "failed": "FAIL", "aborted": "ABORT",
                "partially_succeeded": "FAIL", "rejected": "ABORT"}
    if status in terminal and finished and not finished.startswith("0001-"):
        events.append(dict(base, event_type=terminal[status], event_time=finished))
    return events


def collect(http):
    """Complete API snapshot before doing any Marmot writes or retirement."""
    dags, seen = [], set()
    page = 1
    while True:
        response = http.get("dags", params={"page": page, "perPage": 100})
        response.raise_for_status()
        data = response.json()
        if data.get("errors"):
            raise RuntimeError("Dagu reports invalid definitions; refusing partial sync")
        for dag in data["dags"]:
            filename = dag["fileName"]
            if filename in seen:
                raise RuntimeError("Dagu pagination returned duplicate definitions")
            seen.add(filename)
            if "project=bakery" not in dag["dag"].get("labels", []):
                continue
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", filename):
                raise ValueError("Unsupported DAG filename identity")
            spec = http.get(f"dags/{quote(filename, safe='')}/spec")
            spec.raise_for_status()
            spec = spec.json()
            if spec.get("errors"):
                raise RuntimeError("Invalid DAG spec")
            raw = yaml.safe_load(spec["spec"])
            runs = http.get(f"dags/{quote(filename, safe='')}/dag-runs")
            runs.raise_for_status()
            dags.append((dag, raw, runs.json()["dagRuns"][:20]))
        pagination = data["pagination"]
        if not pagination["hasNextPage"]:
            break
        following = pagination["nextPage"]
        if following <= page or following > 1000:
            raise RuntimeError("Invalid Dagu pagination")
        page = following
    if not dags:
        raise RuntimeError("No Bakery DAGs returned; refusing mass retirement")
    # Child runs are stored under their root run, not necessarily in the
    # child definition's top-level run list. Read their real statuses as well.
    by_name = {dag["fileName"]: executions for dag, _, executions in dags}
    seen_runs = {(name, run["dagRunId"]) for name, executions in by_name.items() for run in executions}
    for dag, spec, executions in dags:
        calls = {step.get("id"): step.get("with", {}).get("dag")
                 for step in spec.get("steps", []) if step.get("action") == "dag.run"}
        if not calls:
            continue
        for index, run in enumerate(list(executions)):
            if "nodes" not in run:
                response = http.get("dag-runs/" + quote(dag["fileName"], safe="") + "/"
                                    + quote(run["dagRunId"], safe=""))
                response.raise_for_status()
                run = response.json()["dagRunDetails"]
                executions[index] = run
            for node in run.get("nodes", []):
                step_id = node["step"].get("id") or node["step"].get("name")
                child_name = calls.get(step_id)
                if not child_name:
                    continue
                if child_name not in by_name:
                    raise ValueError("Unknown child DAG in Bakery orchestration graph")
                for child in node.get("subRuns", []) + node.get("subRunsRepeated", []):
                    child_id = child["dagRunId"]
                    key = (child_name, child_id)
                    if key in seen_runs:
                        continue
                    response = http.get("dag-runs/" + quote(dag["fileName"], safe="") + "/"
                                        + quote(run["dagRunId"], safe="") + "/sub-dag-runs/"
                                        + quote(child_id, safe=""))
                    response.raise_for_status()
                    detail = response.json()["dagRunDetails"]
                    if detail["dagRunId"] != child_id:
                        raise ValueError("Unexpected child run identity")
                    by_name[child_name].append(detail)
                    seen_runs.add(key)
    return dags


def build(dags, observed):
    assets, edges, runs = [], [], []
    names = {dag["fileName"] for dag, _, _ in dags}
    url = os.environ.get("DAGU_UI_URL", "http://localhost:8088").rstrip("/")
    for dag, spec, executions in dags:
        name = dag["fileName"]
        pipeline_mrn = identity("Pipeline", name)
        metadata = {"managed_by": OWNER, "instance": INSTANCE, "lifecycle": "active",
                    "dag_filename": name, "display_name": dag["dag"]["name"],
                    "schedules": dag["dag"].get("schedule", []),
                    "timezone": os.environ.get("TZ", "Asia/Ho_Chi_Minh"),
                    "suspended": dag["suspended"], "next_run": dag.get("nextRun"),
                    "queue": spec.get("queue"), "observed_at": observed}
        latest = dag.get("latestDAGRun")
        if latest and latest.get("dagRunId"):
            metadata["latest_status"] = latest.get("statusLabel")
            metadata["latest_run_id"] = latest.get("dagRunId")
        link = url + "/dags/" + quote(name, safe="")
        assets.append({"name": name, "type": "Pipeline", "providers": ["Dagu"],
                       "description": dag["dag"].get("description", ""), "metadata": metadata,
                       "tags": ["bakery", "dagu"],
                       "external_links": [{"name": "Dagu", "url": link}]})
        steps = spec.get("steps", [])
        ids = [step.get("id") or step.get("name") for step in steps]
        if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", i) for i in ids):
            raise ValueError("Explicit unique safe step IDs are required")
        # Case-fold collisions would map two tasks onto one Marmot MRN.
        if len({i.lower() for i in ids}) != len(ids):
            raise ValueError("Case-insensitive step identity collision")
        for step, step_id in zip(steps, ids):
            task_name = name + "-" + step_id
            task_mrn = identity("Task", task_name)
            assets.append({"name": task_name, "type": "Task", "providers": ["Dagu"],
                           "metadata": {"managed_by": OWNER, "instance": INSTANCE,
                                        "lifecycle": "active", "dag_filename": name,
                                        "step_id": step_id, "observed_at": observed},
                           "tags": ["bakery", "dagu"],
                           "external_links": [{"name": "Dagu", "url": link}]})
            edges.append({"source": pipeline_mrn, "target": task_mrn,
                          "type": "CONTAINS", "job_mrn": pipeline_mrn})
            if step.get("action") == "dag.run":
                child = step.get("with", {}).get("dag")
                if child not in names:
                    raise ValueError("Unknown/unsupported child DAG")
                assets[-1]["metadata"]["child_dag"] = child
                # The invoking task waits for this child pipeline. This is an
                # orchestration dependency, never a fabricated table lineage.
                edges.append({"source": identity("Pipeline", child), "target": task_mrn,
                              "type": "DEPENDS_ON", "job_mrn": pipeline_mrn})
            dependencies = step.get("depends", [])
            if isinstance(dependencies, str):
                dependencies = [dependencies]
            for parent in dependencies:
                if parent not in ids:
                    raise ValueError("Unknown/unsupported step dependency")
                edges.append({"source": identity("Task", name + "-" + parent),
                              "target": task_mrn, "type": "DEPENDS_ON", "job_mrn": pipeline_mrn})
        for run in executions:
            run_id = run["dagRunId"]
            runs.extend(history(pipeline_mrn, name, run_id, run["statusLabel"],
                                run.get("startedAt"), run.get("finishedAt"), observed))
            for node in run.get("nodes", []):
                step_id = node["step"].get("id") or node["step"].get("name")
                if step_id not in ids:
                    continue
                task_name = name + "-" + step_id
                runs.extend(history(identity("Task", task_name), task_name, run_id,
                                    node["statusLabel"], node.get("startedAt"), node.get("finishedAt"), observed))
    return assets, edges, runs


def edge_key(edge):
    return (edge["source"], edge["target"], edge["type"], edge.get("job_mrn"))


def sync():
    headers = {"Authorization": "Bearer " + os.environ["DAGU_TOKEN"]} if os.environ.get("DAGU_TOKEN") else {}
    with httpx.Client(base_url=os.environ.get("DAGU_API", "http://127.0.0.1:8080/api/v1").rstrip("/") + "/",
                      headers=headers, timeout=30) as http:
        snapshot = collect(http)
    assets, edges, runs = build(snapshot, datetime.now(timezone.utc).isoformat())
    previous = json.loads(STATE.read_text()) if STATE.exists() else {"assets": []}
    client = MarmotClient()
    run_id = None
    try:
        client.wait_for_plugins()
        run_id = client.request("POST", "runs/start", json={"pipeline_name": OWNER, "source_name": INSTANCE})["run_id"]
        result = client.request("POST", "runs/assets/batch", json={"pipeline_name": OWNER, "source_name": INSTANCE,
                                "run_id": run_id, "assets": assets, "lineage": edges, "run_history": runs})
        if len(result.get("assets", [])) != len(assets) or any(
                a.get("status") not in {"created", "updated", "unchanged", "existing"} for a in result["assets"]):
            raise RuntimeError("Marmot rejected one or more Dagu assets")
        current = {identity(a["type"], a["name"]): a for a in assets}
        wanted = {edge_key(e) for e in edges}
        # Inspect real edges, including leftovers from an interrupted prior sync.
        owned = set(current) | {a["mrn"] for a in previous["assets"]}
        prune, verified = {}, []
        for mrn in sorted(owned):
            kind, _, name = mrn.removeprefix("mrn://").split("/", 2)
            try:
                asset = client.request("GET", f"assets/lookup/{kind}/Dagu/{quote(name, safe='')}")
            except RuntimeError as exc:
                # A previously managed DAG may have been removed from Marmot
                # independently (for example, after deleting a retired DAG).
                # Treat that missing asset as already pruned and continue
                # reconciling the remaining graph.
                if "Marmot HTTP 404" in str(exc):
                    continue
                raise
            if asset.get("metadata", {}).get("managed_by") != OWNER:
                raise RuntimeError("Refusing to modify an asset owned by another integration")
            graph = client.request("GET", "lineage/assets/" + asset["id"], params={"limit": 1})
            for edge in graph.get("edges", []):
                if (edge["source"] in owned and edge["target"] in owned
                        and edge.get("job_mrn") in owned and edge_key(edge) not in wanted):
                    prune[edge["id"]] = edge
            if mrn in current:
                verified.append({"mrn": mrn, "id": asset["id"]})
            else:
                metadata = dict(asset.get("metadata", {}), lifecycle="retired")
                client.request("PUT", "assets/" + asset["id"], json={"metadata": metadata})
        for edge_id in prune:
            client.request("DELETE", "lineage/direct/" + edge_id)
        # Assert every intended graph edge really exists, not merely HTTP success.
        actual = set()
        for asset in verified:
            graph = client.request("GET", "lineage/assets/" + asset["id"], params={"limit": 1})
            actual.update(edge_key(e) for e in graph.get("edges", []))
        if not wanted.issubset(actual):
            raise RuntimeError("Marmot orchestration graph is incomplete")
        client.request("POST", "runs/complete", json={"run_id": run_id, "status": "completed"})
        temporary = STATE.with_suffix(".tmp")
        temporary.write_text(json.dumps({"assets": verified}, indent=2))
        temporary.replace(STATE)
        return {"pipelines": len(snapshot), "assets": len(assets), "edges": len(edges),
                "run_events": len(runs), "stale_edges_removed": len(prune),
                "retired_assets": len(owned - set(current))}
    except Exception:
        if run_id:
            client.request("POST", "runs/complete", json={"run_id": run_id, "status": "failed",
                           "error": "Dagu metadata sync failed; inspect local logs"})
        raise
    finally:
        client.close()
