"""Shared Marmot REST client and the native dbt snapshot compatibility adapter."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx


class MarmotClient:
    def __init__(self):
        self.http = httpx.Client(
            base_url=os.environ.get("MARMOT_HOST", "http://marmot:8080").rstrip("/") + "/api/v1/",
            headers={"Authorization": "Bearer " + os.environ["MARMOT_API_KEY"]},
            timeout=30,
        )

    def request(self, method, path, **kwargs):
        response = self.http.request(method, path, **kwargs)
        if not response.is_success:
            # Server errors may echo credential-bearing configuration: do not log bodies.
            raise RuntimeError(f"Marmot HTTP {response.status_code}: {method} {path}")
        return response.json() if response.content else None

    def upsert(self, payload):
        schedules = self.request("GET", "ingestion/schedules", params={"limit": 1000})["schedules"]
        matches = [s for s in schedules if s["name"] == payload["name"]]
        if len(matches) > 1:
            raise RuntimeError(f"Duplicate Marmot pipeline: {payload['name']}")
        if matches:
            return self.request("PUT", f"ingestion/schedules/{matches[0]['id']}", json=payload)["id"]
        return self.request("POST", "ingestion/schedules", json=payload)["id"]

    def wait_for_plugins(self, required=("dbt",), timeout=600):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.http.get("plugins")
            if response.status_code in {502, 503}:
                time.sleep(5)
                continue
            response.raise_for_status()
            state = response.json()
            missing = set(required) - {p["id"] for p in state.get("plugins", [])}
            if not state.get("loading", False):
                if missing:
                    raise RuntimeError("Marmot plugins unavailable: " + ", ".join(sorted(missing)))
                return
            time.sleep(5)
        raise TimeoutError("Marmot plugins are still loading; inspect server logs.")

    def trigger_and_wait(self, schedule_id, timeout=600):
        run = self.request("POST", f"ingestion/schedules/{schedule_id}/trigger")
        run_id = run["id"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = self.request("GET", f"ingestion/runs/{run_id}")
            status = str(run["status"]).lower()
            if status in {"completed", "success", "succeeded"}:
                return {"run_id": run_id, "status": status}
            if status in {"failed", "cancelled", "canceled"}:
                raise RuntimeError(f"Marmot ingestion {run_id} ended {status}; inspect Marmot run logs.")
            time.sleep(3)
        raise TimeoutError(f"Marmot ingestion {run_id} did not finish within {timeout}s")

    def close(self):
        self.http.close()

    def verify_catalog(self, manifest):
        # Ingestion "succeeded" alone is insufficient: some plugin versions log
        # missing lineage endpoints but still mark their ingestion successful.
        tables = models = snapshots = 0
        for node in manifest["nodes"].values():
            kind = node["resource_type"]
            if kind not in {"model", "snapshot"}:
                continue
            fqn = f"{node['database']}.{node['schema']}.{node['alias']}"
            table = self.request("GET", "assets/lookup/Table/Postgres/" + fqn)
            tables += 1
            if kind == "model":
                self.request("GET", "assets/lookup/Model/DBT/" + fqn)
                models += 1
            else:
                graph = self.request("GET", "lineage/assets/" + table["id"], params={"limit": 1})
                edges = {(e["source"], e["target"]) for e in graph["edges"]}
                for parent_id in node["depends_on"]["nodes"]:
                    parent = manifest["nodes"][parent_id]
                    parent_fqn = f"{parent['database']}.{parent['schema']}.{parent['alias']}"
                    if ("mrn://table/postgres/" + parent_fqn.lower(), table["mrn"]) not in edges:
                        raise RuntimeError("Missing staging -> snapshot catalog lineage")
                for child in manifest["nodes"].values():
                    if child["resource_type"] == "model" and node["unique_id"] in child.get("depends_on", {}).get("nodes", []):
                        child_fqn = f"{child['database']}.{child['schema']}.{child['alias']}"
                        if (table["mrn"], "mrn://model/dbt/" + child_fqn.lower()) not in edges:
                            raise RuntimeError("Missing snapshot -> dimension catalog lineage")
                snapshots += 1
        return {"tables": tables, "models": models, "snapshot_paths": snapshots}

    def snapshot_assets(self, manifest, catalog):
        """Compatibility for dbt plugin 0.1.1: it skips resource_type=snapshot.

        Create only the missing physical history tables using the same identity
        as the dbt plugin, so its snapshot -> dimension edges can resolve.
        Staging -> snapshot edges are added after native model ingestion.
        """
        assets, edges = [], []
        for key, node in manifest["nodes"].items():
            if node["resource_type"] != "snapshot":
                continue
            if node["schema"] != "analytics_mart":
                raise RuntimeError("Snapshot outside analytics_mart")
            fqn = f"{node['database']}.{node['schema']}.{node['alias']}"
            assets.append({
                "name": fqn, "type": "Table", "providers": ["Postgres"],
                "description": node.get("description") or "dbt technical SCD2 snapshot history",
                "metadata": {"database": node["database"], "schema": node["schema"],
                             "table_name": node["alias"], "dbt_unique_id": key,
                             "resource_type": "snapshot", "compatibility": "marmot-dbt-0.1.1"},
                "tags": ["bakery", "dbt-snapshot", "analytics"],
                "schema": {"dbt": json.dumps(list(catalog.get("nodes", {}).get(key, {}).get("columns", {}).values()))},
            })
            for parent_id in node.get("depends_on", {}).get("nodes", []):
                parent = manifest["nodes"].get(parent_id)
                if parent is None or parent["resource_type"] != "model":
                    raise RuntimeError("Unexpected snapshot dependency")
                parent_fqn = f"{parent['database']}.{parent['schema']}.{parent['alias']}"
                edges.append({"source": "mrn://table/postgres/" + parent_fqn.lower(),
                              "target": "mrn://table/postgres/" + fqn.lower(), "type": "DEPENDS_ON"})
        if not assets:
            return []
        name = "bakery-dbt-snapshot-compatibility"
        run_id = self.request("POST", "runs/start", json={"pipeline_name": name, "source_name": name})["run_id"]
        try:
            self.request("POST", "runs/assets/batch", json={"pipeline_name": name, "source_name": name,
                         "run_id": run_id, "assets": assets})
            self.request("POST", "runs/complete", json={"run_id": run_id, "status": "completed"})
        except Exception:
            self.request("POST", "runs/complete", json={"run_id": run_id, "status": "failed", "error": "Snapshot catalog compatibility failed"})
            raise
        return edges
