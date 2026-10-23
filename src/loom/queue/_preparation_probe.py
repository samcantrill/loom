"""Run real preparation in a selected installation without publishing a run."""

from __future__ import annotations

from collections.abc import Mapping

from loom.serialization import PlainData

from ._agent_process_supervisor import ResidentWorkerLaunchProfile
from ._resident_probe import run_resident_probe
from .errors import QueueConflictError
from .shared_execution import _preparation_input_roots
from .preparation import (
    PREPARATION_CONTEXT_SCHEMA_VERSION,
    PreparationChildInput,
    SharedInputReceipt,
    _require_local_binding,
    _scope_data,
    resolve_shared_input,
)


# Send the fixed script to the selected installation. Its installed preparation
# implementation owns composition, project hooks and preflight semantics.
_SCRIPT = '''
import json, os, sys, tempfile
from pathlib import Path
from loom.diagnostics.models import PreflightResult
from loom.pipeline.context import StageContext
from loom.pipeline.specs import OutputSpec
from loom.pipeline.stores import LocalArtifactStore
from loom.preparation import PreparationStage, preparation_checks_allow_publication
from loom.queue.preparation import PREPARATION_INPUT_CONTEXT_ENV

request = json.loads(sys.argv[1])
os.environ[PREPARATION_INPUT_CONTEXT_ENV] = json.dumps(request["context"])
with tempfile.TemporaryDirectory(prefix="loom-preparation-probe-", dir="/tmp") as directory:
    root = Path(directory)
    store = LocalArtifactStore(root / "artifacts")
    context = StageContext(
        run_uri=root.as_uri(), stage_name="prepare", resolved_config={},
        stage_config=request["binding"], artifact_store=store,
        output_specs={"report": OutputSpec("json", "json.v1")},
        local_output_dir=root / "outputs", local_workspace_dir=root / "workspace",
    )
    try:
        outputs = PreparationStage().run(context, {})
        report = store.load(outputs["report"])
        preflight = PreflightResult.from_dict(report["preflight"])
        result = {
            "allowed": preparation_checks_allow_publication(preflight),
            "preflight": report["preflight"],
            "input_manifest_digest": report["input_manifest_digest"],
            **({"execution": report["execution"], "container_capability": report["container_capability"]}
               if "execution" in report else {"profile_descriptor": report["profile_descriptor"]}),
        }
    except Exception as exc:
        result = {"allowed": False, "error_type": type(exc).__name__}
    print(json.dumps(result))
'''


def probe_preparation(
    profile: ResidentWorkerLaunchProfile,
    binding: PreparationChildInput,
    *,
    agent_id: str,
) -> Mapping[str, PlainData]:
    """Check captured preparation in the candidate; do not execute its pipeline.

    The same installed stage and protected shared/local policy used by real
    preparation are exercised. Only ephemeral report artifacts are written.
    A bounded, contained failure refuses compatibility before maintenance.
    """
    if binding.execution is not None:
        if (profile.submitted_execution != binding.execution
            or binding.container_capability is None
            or dict(profile.descriptor) != binding.container_capability.to_dict()):
            raise QueueConflictError("preparation candidate submitted execution differs")
    elif binding.profile_descriptor is None or dict(binding.profile_descriptor) != dict(profile.descriptor):
        raise QueueConflictError("preparation candidate installation differs")
    _require_local_binding(binding.local_scope, profile, agent_id=agent_id)
    if not isinstance(binding.input_receipt, SharedInputReceipt):
        raise QueueConflictError("preparation probe requires shared captured input")
    resolve_shared_input(
        binding.input_receipt, shared_roots=profile.preparation_shared_roots,
    )
    if binding.shared_scope is not None:
        from .shared_execution import require_bindings

        require_bindings(binding.shared_scope, profile.shared_roots)
    purpose: dict[str, PlainData] = {"kind": "generic"}
    if binding.project_preparation is not None:
        purpose = {"kind": "project", "binding": dict(binding.project_preparation)}
    context: dict[str, PlainData] = {
        "schema_version": 7 if binding.execution is not None else PREPARATION_CONTEXT_SCHEMA_VERSION,
        **binding.execution_data(),
        "scope": _scope_data(binding.local_scope, binding.shared_scope),
        "purpose": purpose,
        "input": {"kind": "shared", "roots": _preparation_input_roots(profile, binding)},
    }
    result = run_resident_probe(
        profile, _SCRIPT, {"binding": binding.to_dict(), "context": context},
        timeout_seconds=120, preparation=binding,
    )
    if result.failure is not None or not result.contained or result.payload is None:
        raise QueueConflictError("candidate preparation probe failed: " + str(result.failure))
    if result.payload.get("allowed") is not True:
        raise QueueConflictError("candidate preparation is incompatible: " + str(dict(result.payload)))
    if (
        any(result.payload.get(key) != value for key, value in binding.execution_data().items())
        or result.payload.get("input_manifest_digest") != binding.input_receipt.manifest_digest
    ):
        raise QueueConflictError("candidate preparation evidence differs")
    return result.payload
