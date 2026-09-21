"""Installed, standard-library-only project fixture for native node contracts."""

from copy import deepcopy
from pathlib import Path
import time


def inspect(request):
    from loom.fingerprints import hash_mapping
    from loom.artifacts import ArtifactRef
    from loom.pipeline.stores import LocalArtifactStore

    assert request["schema_version"] == 3
    if request["operation"] == "verify_result":
        candidate = request["candidate"]
        assert request["contract"]["semantic_key"] == candidate["semantic_key"]
        assert request["contract"]["namespace"] == candidate["namespace"] == "text-project"
        store = LocalArtifactStore(Path.cwd())
        assert request["artifact_access"]["mode"] == "read_only"
        for fact in candidate["result"]["artifact_facts"]:
            materialized = request["artifact_access"]["outputs"][fact["artifact_name"]]
            assert materialized["artifact_id"] == fact["artifact"]["artifact_id"]
            product = store.load(ArtifactRef.from_dict(materialized))
            if product not in ("alpha\nbeta\n", 2):
                return {"schema_version": 1, "candidate_digest": candidate["candidate_digest"],
                        "verdict": "rejected", "reason": {"code": "line_count_mismatch", "output_port": fact["artifact_name"]}}
        return {"schema_version": 1, "candidate_digest": candidate["candidate_digest"], "verdict": "verified"}
    if request["operation"] == "verify_candidate":
        candidate = request["candidate"]
        desired = request["project_result"]["stage_contracts"]
        assert set(candidate["project_contracts"]) == set(desired)
        for name, attachment in candidate["project_contracts"].items():
            assert attachment["namespace"] == "text-project"
            assert {
                key: attachment[key] for key in ("semantic_key", "payload")
            } == desired[name]
        if candidate["authority"]["status"] == "SUCCEEDED":
            store = LocalArtifactStore(Path(candidate["artifact_binding"]["root"]))
            for stage in candidate["authority"]["stages"]:
                assert stage["status"] == "SUCCEEDED"
                for fact in stage["artifact_facts"]:
                    product = store.load(ArtifactRef.from_dict(fact["artifact"]))
                    assert product in ("alpha\nbeta\n", 2)
        return {
            "schema_version": 1,
            "candidate_digest": hash_mapping(candidate),
            "verdict": "verified",
        }
    composition = deepcopy(request["composition"])
    contracts = {}
    for stage in composition["resolved"]["pipeline"]["stages"]:
        contracts[stage["name"]] = {
            "semantic_key": None
            if stage["config"].get("opt_out")
            else {
                "version": 1,
                "digest": hash_mapping(stage["config"]).split(":", 1)[1],
            },
            "payload": {
                "ordered_outputs": [{"ports": list(stage["outputs"])}],
                "declaration": stage["config"],
                "node": stage["name"],
                "opaque_location": {
                    "kind": "location",
                    "root": "unregistered",
                    "path": "/opaque/project/path",
                },
            },
        }
    return {
        "schema_version": 3,
        "composition": composition,
        "evidence": {
            "namespace": "text-project",
            "payload": {"nodes": list(contracts)},
        },
        "reconciliation_key": {
            "namespace": "text-project",
            "version": 1,
            "digest": hash_mapping(composition["resolved"]["pipeline"]).split(":", 1)[1],
        },
        "stage_contracts": contracts,
    }


def _checked(context, allowed):
    assert set(context.stage_config) <= allowed
    attachment = context.metadata["loom.project_contract"]
    assert attachment["payload"]["declaration"] == dict(context.stage_config)
    assert attachment["payload"]["node"] == context.stage_name
    assert attachment["payload"]["opaque_location"] == {
        "kind": "location",
        "root": "unregistered",
        "path": "/opaque/project/path",
    }
    assert "loom.project_contracts" not in context.metadata
    assert "loom.project_contract_capture" not in context.metadata
    binding = context.metadata["loom.execution_binding"]
    assert binding["origin_node_id"] == context.stage_name
    assert binding["run_state_root"] is not None
    assert context.run_uri.startswith("loom-agent:")
    return binding


class GenerateText:
    def run(self, context, inputs):
        binding = _checked(context, {"delay", "fail_once", "value"})
        directory = (
            Path(binding["run_state_root"]) / "actions" / binding["origin_node_id"]
        )
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / "started"
        marker.touch()
        if context.stage_config.get("fail_once") and binding["attempt"] == 1:
            raise RuntimeError("fixture first attempt failure")
        time.sleep(context.stage_config.get("delay", 0))
        value = context.stage_config.get("value", "alpha\nbeta\n")
        return {
            "text": context.save_artifact(
                "text", value, artifact_type="json", codec_key="json.v1"
            )
        }


class CountLines:
    def run(self, context, inputs):
        _checked(context, {"opt_out", "fail"})
        if context.stage_config.get("fail"):
            raise RuntimeError("fixture count failure")
        text = context.load_artifact(inputs["text"])
        value = len(text.splitlines())
        return {
            "count": context.save_artifact(
                "count", value, artifact_type="json", codec_key="json.v1"
            )
        }
