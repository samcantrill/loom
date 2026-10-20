"""Tiny project copied into acceptance images, never mounted from the host."""

from copy import deepcopy
import os
from pathlib import Path
import socket
from time import monotonic, sleep
from uuid import uuid4

VALUE = 11
PROCESS_ID = str(uuid4())


def inspect(request):
    """Prove project preparation imports the selected implementation."""
    from loom.fingerprints import hash_mapping
    from loom.queue.submitted_execution import submitted_binding, submitted_implementation

    assert request["schema_version"] == 3
    if request["operation"] == "verify_candidate":
        candidate = request["candidate"]
        for contract in candidate["project_contracts"].values():
            assert contract["payload"]["value"] == VALUE
        # Match shared preparation's contract: candidate URIs are provenance,
        # not an export of the whole artifact root. The harness checks outputs.
        expected, capability = submitted_binding(
            {key: request[key] for key in ("execution", "container_capability")}
        )
        implementation = submitted_implementation(expected, capability)
        for stage in candidate["configuration"]["pipeline"]["stages"]:
            assert submitted_implementation(*submitted_binding(
                stage["fingerprint"]["loom.submitted_execution"]
            )) == implementation
        assert candidate["native_intent"]["execution_requirements"] == {
            name: capability.requirement(expected).to_dict()
            for name in candidate["project_contracts"]
        }
        return {"schema_version": 1, "candidate_digest": hash_mapping(candidate),
                "verdict": "verified"}
    composition = deepcopy(request["composition"])
    evidence = {"value": VALUE, "prepared_process": PROCESS_ID,
                "prepared_host": socket.gethostname()}
    binding = submitted_binding({key: request[key] for key in ("execution", "container_capability")})
    return {
        "schema_version": 3,
        "composition": composition,
        "evidence": {"namespace": "submitted-probe", "payload": evidence},
        "reconciliation_key": {
            "namespace": "submitted-probe", "version": 1,
            "digest": hash_mapping({
                "pipeline": composition["resolved"]["pipeline"],
                "implementation": submitted_implementation(*binding),
            }).split(":", 1)[1],
        },
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
        gpu = None
        if context.stage_config.get("gpu_compute"):
            from submitted_container_cuda import compute
            gpu = compute()
        control = Path(os.environ["PROBE_CONTROL"])
        if context.stage_config.get("fail_once") and not (control / f"failed-{VALUE}").exists():
            (control / f"failed-{VALUE}").touch()
            raise RuntimeError("one observed fixture failure")
        if context.stage_config.get("barrier"):
            (control / "started-a").write_text(str(os.getpid()))
            deadline = monotonic() + 180
            while not (control / "release-a").exists():
                if monotonic() > deadline:
                    raise TimeoutError("acceptance barrier was not released")
                sleep(0.05)
        return {"data": context.save_artifact(
            "data", {**evidence, "execution_pid": os.getpid(),
                     "execution_host": socket.gethostname(), "gpu": gpu},
            artifact_type="json", codec_key="json.v1",
        )}


if VALUE == 29:
    class NewStage(Probe):
        """This target exists only in the second image."""
