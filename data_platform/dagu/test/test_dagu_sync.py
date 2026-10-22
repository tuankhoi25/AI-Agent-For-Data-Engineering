import unittest
from unittest.mock import patch
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import json

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dagu_sync import OWNER, build, collect, history, identity, sync


class DaguMetadataTests(unittest.TestCase):
    def sample(self):
        return ({"fileName": "bakery-test", "dag": {"name": "Display name", "schedule": []},
                 "suspended": False}, {"steps": [{"id": "a", "run": "secret command"},
                                                  {"id": "b", "depends": ["a"]}]}, [])

    def test_static_graph_without_any_execution(self):
        assets, edges, events = build([self.sample()], "now")
        self.assertEqual((len(assets), len(edges), len(events)), (3, 3, 0))
        self.assertNotIn("secret command", str(assets))
        self.assertEqual(edges[-1]["type"], "DEPENDS_ON")
        self.assertEqual(edges[-1]["source"], "mrn://task/dagu/bakery-test-a")

    def test_case_collision_rejected(self):
        dag, spec, runs = self.sample()
        spec["steps"] = [{"id": "A"}, {"id": "a"}]
        with self.assertRaises(ValueError):
            build([(dag, spec, runs)], "now")

    def test_invalid_dependency_rejected_before_writes(self):
        dag, spec, runs = self.sample()
        spec["steps"][1]["depends"] = ["missing"]
        with self.assertRaises(ValueError):
            build([(dag, spec, runs)], "now")

    def test_child_pipeline_is_a_real_orchestration_dependency(self):
        dag, spec, runs = self.sample()
        spec["steps"] = [{"id": "child", "action": "dag.run", "with": {
            "dag": "bakery-child", "params": {"BATCH_ID": "private-parameter"}}}]
        child = ({"fileName": "bakery-child", "dag": {"name": "bakery-child"}, "suspended": False},
                 {"steps": [{"id": "build", "run": "private-command"}]}, [])
        assets, edges, _ = build([(dag, spec, runs), child], "now")
        self.assertIn({"source": identity("Pipeline", "bakery-child"),
                       "target": identity("Task", "bakery-test-child"),
                       "type": "DEPENDS_ON", "job_mrn": identity("Pipeline", "bakery-test")}, edges)
        self.assertNotIn("private-parameter", str(assets))
        self.assertNotIn("private-command", str(assets))

    def test_unknown_child_refuses_partial_metadata_graph(self):
        dag, spec, runs = self.sample()
        spec["steps"] = [{"id": "child", "action": "dag.run", "with": {"dag": "missing"}}]
        with self.assertRaises(ValueError):
            build([(dag, spec, runs)], "now")

    def test_collect_reads_child_run_from_root_detail_endpoint(self):
        root_spec = {"steps": [{"id": "child", "action": "dag.run", "with": {"dag": "bakery-child"}}]}
        definitions = [
            {"fileName": name, "dag": {"name": name, "labels": ["project=bakery"]}, "suspended": False}
            for name in ("bakery-parent", "bakery-child")]
        child_run = {"dagRunId": "child-run", "statusLabel": "succeeded", "startedAt": "start", "finishedAt": "end"}
        root_run = {"dagRunId": "root-run", "statusLabel": "succeeded", "nodes": [
            {"step": {"id": "child"}, "statusLabel": "succeeded",
             "subRuns": [{"dagRunId": "child-run"}]}]}
        requests = []
        def handler(request):
            path = request.url.path.lstrip("/")
            requests.append(path)
            responses = {
                "dags": {"dags": definitions, "pagination": {"hasNextPage": False}},
                "dags/bakery-parent/spec": {"spec": yaml.safe_dump(root_spec)},
                "dags/bakery-child/spec": {"spec": "steps: [{id: build}]"},
                "dags/bakery-parent/dag-runs": {"dagRuns": [{"dagRunId": "root-run"}]},
                "dags/bakery-child/dag-runs": {"dagRuns": []},
                "dag-runs/bakery-parent/root-run": {"dagRunDetails": root_run},
                "dag-runs/bakery-parent/root-run/sub-dag-runs/child-run": {"dagRunDetails": child_run},
            }
            return httpx.Response(200, json=responses[path])
        with httpx.Client(base_url="http://dagu/", transport=httpx.MockTransport(handler)) as client:
            snapshot = collect(client)
        self.assertEqual(snapshot[1][2], [child_run])
        self.assertIn("dag-runs/bakery-parent/root-run/sub-dag-runs/child-run", requests)
        _, _, events = build(snapshot, "now")
        self.assertTrue(any(event["asset_mrn"] == identity("Pipeline", "bakery-child")
                            and event["event_type"] == "COMPLETE" for event in events))

    def test_running_never_marked_complete(self):
        events = history("mrn", "task", "id", "running", "2026-10-22T01:00:00Z", None, "now")
        self.assertEqual([e["event_type"] for e in events], ["START"])

    def test_queued_has_no_invented_execution(self):
        self.assertEqual(history("m", "t", "id", "queued", "", "", "now"), [])

    def test_repeat_has_stable_run_id(self):
        a = history("m", "t", "id", "succeeded", "start", "end", "now")
        b = history("m", "t", "id", "succeeded", "start", "end", "later")
        self.assertEqual(a[0]["run_id"], b[0]["run_id"])
        self.assertEqual([e["event_type"] for e in a], ["START", "COMPLETE"])

    def test_empty_snapshot_refuses_retirement(self):
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"dags": [], "pagination": {"hasNextPage": False}}))
        with httpx.Client(base_url="http://dagu/", transport=transport) as client:
            with self.assertRaises(RuntimeError):
                collect(client)

    def test_pagination_reads_all_pages(self):
        pages = []
        def handler(request):
            page = int(request.url.params["page"])
            pages.append(page)
            dag = {"fileName": f"bakery-{page}", "dag": {"labels": []}}
            return httpx.Response(200, json={"dags": [dag], "pagination": {
                "hasNextPage": page == 1, "nextPage": 2}})
        with httpx.Client(base_url="http://dagu/", transport=httpx.MockTransport(handler)) as client:
            # Both pages read; non-Bakery labels mean fail-closed, not an empty prune.
            with self.assertRaises(RuntimeError):
                collect(client)
        self.assertEqual(pages, [1, 2])

    def test_stale_owned_edges_pruned_and_missing_task_retired(self):
        dag, spec, executions = self.sample()
        assets, edges, _ = build([(dag, spec, executions)], "now")
        old = identity("Task", "bakery-test-retired")
        wanted = {identity(a["type"], a["name"]): a for a in assets}
        stale = {"id": "stale-edge", "source": old,
                 "target": identity("Task", "bakery-test-b"),
                 "type": "DEPENDS_ON", "job_mrn": identity("Pipeline", "bakery-test")}
        unrelated = dict(stale, id="unowned-edge", job_mrn="mrn://pipeline/other/owner")

        class FakeMarmot:
            def __init__(self):
                self.deleted, self.retired = [], []
            def wait_for_plugins(self):
                pass
            def close(self):
                pass
            def request(self, method, path, **kwargs):
                if path == "runs/start":
                    return {"run_id": "test"}
                if path == "runs/assets/batch":
                    return {"assets": [{"status": "updated"} for _ in assets]}
                if path.startswith("assets/lookup/"):
                    name = path.rsplit("/", 1)[-1]
                    kind = path.split("/")[2]
                    return {"id": identity(kind, name), "metadata": {"managed_by": OWNER}}
                if path.startswith("lineage/assets/"):
                    return {"edges": edges + ([] if self.deleted else [stale]) + [unrelated]}
                if method == "DELETE":
                    self.deleted.append(path.rsplit("/", 1)[-1])
                if method == "PUT":
                    self.retired.append(kwargs["json"]["metadata"]["lifecycle"])
                return {}
        fake = FakeMarmot()
        with TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(json.dumps({"assets": [{"mrn": old}]}))
            with patch("dagu_sync.STATE", state), patch("dagu_sync.collect", return_value=[(dag, spec, executions)]), patch("dagu_sync.MarmotClient", return_value=fake):
                result = sync()
            self.assertEqual(fake.deleted, ["stale-edge"])
            self.assertEqual(fake.retired, ["retired"])
            self.assertEqual(result["retired_assets"], 1)
            self.assertEqual({a["mrn"] for a in json.loads(state.read_text())["assets"]}, set(wanted))


if __name__ == "__main__":
    unittest.main()
