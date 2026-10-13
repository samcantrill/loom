"""Installed synthetic shared-input consumer and preparation processor."""
from copy import deepcopy
from pathlib import Path
import hashlib
import os


def inspect_shared(request):
    assert request["shared_scope"]["capability"] == "shared-execution-v1"
    assert "local_scope" not in request
    composition = deepcopy(request["composition"])
    evidence = {"prepared_pid": os.getpid(), "scope": "shared"}
    for view in ("resolved", "redacted"):
        composition[view]["scientific_evidence"] = evidence
    return {"schema_version": 1, "composition": composition,
            "evidence": {"namespace": "shared-example", "payload": evidence},
            "reconciliation_key": None}


class SharedInputConsumer:
    def run(self, context, inputs):
        assert not inputs
        data = Path(context.stage_config["input"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == context.stage_config["expected"]
        print("shared-input", hashlib.sha256(data).hexdigest(), "pid", os.getpid())
        return {"receipt": context.save_artifact("receipt", {"digest": hashlib.sha256(data).hexdigest(), "execution_pid": os.getpid()}, artifact_type="json", codec_key="json.v1")}


class SharedClosureProducer:
    def run(self, context, inputs):
        _check_project_context(context)
        assert not inputs
        root = context.local_output_path("manifest", suffix=".json").parent
        block = b"shared-native-payload\n" * 4096
        size = 0
        digest = hashlib.sha256()
        with (root / "values.bin").open("wb") as stream:
            while size <= 64 * 1024 * 1024:
                stream.write(block)
                digest.update(block)
                size += len(block)
        (root / "sample_ids.json").write_text('["sample-1"]')
        (root / "checkpoints").mkdir()
        (root / "checkpoints" / "checkpoint.bin").write_bytes(b"checkpoint-bytes")
        (root / "checkpoints" / "catalog.json").write_text('{"member":"checkpoint.bin"}')
        return {"manifest": context.save_artifact("manifest", {
            "payload": "values.bin", "ids": "sample_ids.json", "catalog": "checkpoints/catalog.json",
            "size": size, "digest": digest.hexdigest(), "producer_pid": os.getpid(),
        }, artifact_type="json", codec_key="json.v1")}


class SharedClosureConsumer:
    def run(self, context, inputs):
        _check_project_context(context)
        from loom.io.uris import uri_to_path
        import json
        manifest = context.load_input("manifest")
        root = uri_to_path(context.input_artifact("manifest").uri).parent
        digest = hashlib.sha256()
        size = 0
        with (root / manifest["payload"]).open("rb") as stream:
            while data := stream.read(1024 * 1024):
                size += len(data)
                digest.update(data)
        assert size == manifest["size"] and digest.hexdigest() == manifest["digest"]
        assert json.loads((root / manifest["ids"]).read_text()) == ["sample-1"]
        catalog = root / manifest["catalog"]
        assert (catalog.parent / json.loads(catalog.read_text())["member"]).read_bytes() == b"checkpoint-bytes"
        assert os.getpid() != manifest["producer_pid"]
        return {"receipt": context.save_artifact("receipt", {
            "digest": digest.hexdigest(), "size": size, "consumer_pid": os.getpid(),
            "producer_pid": manifest["producer_pid"],
        }, artifact_type="json", codec_key="json.v1")}


class SharedRecoveryProducer:
    """Synthetic complete progress followed by ordinary failure or root death."""

    def run(self, context, inputs):
        import json
        binding = context.metadata["loom.recovery_binding"]
        execution = context.metadata["loom.execution_binding"]
        current = Path(binding["current"]["path"])
        assert execution["run_state_root"] is None
        assert current.is_dir()
        assert not inputs
        if execution["attempt"] == 1:
            assert not binding["predecessors"]
            (current / "checkpoint").mkdir()
            (current / "checkpoint" / "weights").write_bytes(b"completed-progress")
            (current / "catalog.json").write_text('{"checkpoint":"checkpoint/weights"}')
            (current / "partial").write_bytes(b"incomplete-progress")
            if context.stage_config["death"]:
                os._exit(19)
            raise RuntimeError("synthetic failure after complete progress")
        assert execution["attempt"] == 2
        assert len(binding["predecessors"]) == 1
        prior = binding["predecessors"][0]
        assert prior["attempt"] == 1
        previous = Path(prior["path"])
        assert previous != current
        catalog = json.loads((previous / "catalog.json").read_text())
        assert (previous / catalog["checkpoint"]).read_bytes() == b"completed-progress"
        (current / "restored").write_bytes(b"restored")
        return {"manifest": context.save_artifact("manifest", {"restored": True, "binding": binding}, artifact_type="json", codec_key="json.v1")}


def inspect_shared_context(request):
    """Write one metadata companion into the native publication closure."""
    root = Path(request["artifact_directory"])
    (root / "science.json").write_text('science belongs to preparation')
    stages = request["composition"]["resolved"]["pipeline"]["stages"]
    return {
        "schema_version": 3,
        "composition": request["composition"],
        "evidence": {"namespace": "shared-context", "payload": {}},
        "reconciliation_key": None,
        "stage_contracts": {
            stage["name"]: {"semantic_key": None, "payload": {"member": "science.json"}}
            for stage in stages
        },
    }


def _check_project_context(context):
    if not context.stage_config.get("project_context"):
        return
    from loom.artifacts import ArtifactRef
    from loom.io.uris import uri_to_path
    from loom.serialization import thaw_plain_data

    reference = ArtifactRef.from_dict(thaw_plain_data(context.metadata["loom.project_report"]))
    report = context.load_artifact(reference)
    contract = report["project_contracts"][context.stage_name]
    assert contract == thaw_plain_data(context.metadata["loom.project_contract"])
    root = uri_to_path(reference.uri).parent
    assert (root / contract["payload"]["member"]).read_text() == 'science belongs to preparation'
