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
