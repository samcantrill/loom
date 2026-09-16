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
