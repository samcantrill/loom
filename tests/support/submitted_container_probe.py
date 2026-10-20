"""Tiny project copied into acceptance images, never mounted from the host."""

from copy import deepcopy
import os
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

VALUE = 11
PROCESS_ID = str(uuid4())


def inspect(request):
    """Prove project preparation imports the selected implementation."""
    assert request["schema_version"] == 3
    composition = deepcopy(request["composition"])
    evidence = {"value": VALUE, "prepared_process": PROCESS_ID}
    return {
        "schema_version": 3,
        "composition": composition,
        "evidence": {"namespace": "submitted-probe", "payload": evidence},
        "reconciliation_key": None,
        "stage_contracts": {
            stage["name"]: {"semantic_key": None, "payload": evidence}
            for stage in composition["resolved"]["pipeline"]["stages"]
        },
    }


class Probe:
    def run(self, context, inputs):
        assert not inputs
        evidence = context.metadata["loom.project_contract"]["payload"]
        assert evidence["value"] == VALUE
        # Separate PID namespaces can assign the same numeric PID.
        assert evidence["prepared_process"] != PROCESS_ID
        control = Path(os.environ["PROBE_CONTROL"])
        if context.stage_config.get("barrier"):
            (control / "started-a").write_text(str(os.getpid()))
            deadline = monotonic() + 180
            while not (control / "release-a").exists():
                if monotonic() > deadline:
                    raise TimeoutError("acceptance barrier was not released")
                sleep(0.05)
        return {"data": context.save_artifact(
            "data", {**evidence, "execution_pid": os.getpid()},
            artifact_type="json", codec_key="json.v1",
        )}


if VALUE == 29:
    class NewStage(Probe):
        """This target exists only in the second image."""
