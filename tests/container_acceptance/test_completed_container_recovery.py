"""Opt-in completed-worker recovery with synthetic inputs and an installed SIF."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from time import monotonic, sleep

import pytest

from loom.pipeline.planning import StageFingerprintRecord
from loom.pipeline.status import StageStatus
from loom.pipeline.execution.stage_worker import StageWorkerResult
from loom.io.uris import uri_to_path
from loom.queue._agent_process_supervisor import (
    SupervisorLaunchState,
    _launch_value,
)
from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
from loom.queue._shared_publication import publish
from loom.queue.shared_execution import (
    SHARED_EXECUTION_SCOPE,
    qualifications,
    stage_scope,
)
from tests.container_acceptance.test_real_container_runtimes import (
    _required_apptainer_resource_command,
)
from tests.unit.loom.queue.test_agent_process_supervisor import (
    _ipc_owner,
    _retain_shared_launch,
    _shared_container_request,
)


pytestmark = [pytest.mark.slow, pytest.mark.optional_dependency]


def test_real_completed_container_publishes_without_original_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("LOOM_RUN_APPTAINER_TIMEOUT_ACCEPTANCE") != "1":
        pytest.skip("enable the installed-image namespace acceptance lane")
    image = os.environ.get("LOOM_APPTAINER_RESOURCE_IMAGE", "")
    python = os.environ.get("LOOM_APPTAINER_WORKER_PYTHON", "")
    assert image and Path(image).is_file(), "select an approved local SIF"
    assert python and Path(python).is_absolute(), "select its installed Python"
    command = _required_apptainer_resource_command()

    resident, request, data = _shared_container_request(tmp_path)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "challenge").write_bytes(b"outputs")
    roots = {
        **resident.shared_roots,
        "outputs": {
            "host_path": str(outputs), "container_path": "/loom/outputs",
            "access": "rw",
            "challenge": {
                "path": "challenge",
                "sha256": hashlib.sha256(b"outputs").hexdigest(),
            },
            "publication": {
                "max_members": 16, "max_payload_bytes": 1048576,
                "max_manifest_bytes": 65536,
            },
        },
    }
    installed = tmp_path / "installed-fixture"
    installed.mkdir()
    # Only this synthetic project is inserted into the image interpreter's path.
    # Loom itself remains the image's installed worker implementation.
    (installed / "python").write_text(
        f"#!{python}\n"
        "import runpy,sys\n"
        "sys.path.insert(0, '/fixture/source')\n"
        "module=sys.argv.pop(2); sys.argv.pop(1)\n"
        "runpy.run_module(module, run_name='__main__')\n"
    )
    (installed / "python").chmod(0o700)
    (installed / "pkg.py").write_text(
        "from pathlib import Path\n"
        "class Stage:\n"
        "    def run(self, context, inputs):\n"
        "        assert Path(context.stage_config['input'], 'payload.bin').read_bytes() == b'synthetic input'\n"
        "        counter=context.local_workspace_path('executions.txt')\n"
        "        with counter.open('a') as stream: stream.write('execution\\n')\n"
        "        output=context.local_output_path('result', suffix='.bin')\n"
        "        output.write_bytes(b'qualified synthetic output')\n"
        "        return {'result': context.register_local_artifact('result', output, artifact_type='bytes')}\n"
    )
    resident = replace(resident, shared_roots=roots, container={
        "kind": "apptainer",
        "container": {
            "image": {"reference": image},
            "mounts": [{
                "source": str(installed), "target": "/fixture/source", "mode": "ro",
            }],
        },
        "options": {"command": command},
        "python_executable": "/fixture/source/python", "daemon_endpoint": None,
    })
    fingerprint = StageFingerprintRecord.from_dict(request.fingerprint)
    selection = {"input": {
        "kind": "loom.shared-location", "schema_version": 1,
        "root_id": "data", "path": ".",
    }}
    scope = stage_scope(selection, {}, {"roots": qualifications(roots)})
    request = replace(request, profile=resident.descriptor, fingerprint=StageFingerprintRecord.create(
        algorithm=fingerprint.algorithm,
        payload=replace(
            fingerprint.payload, factory_target="pkg.Stage", stage_config=selection,
            fingerprint_fields={SHARED_EXECUTION_SCOPE: scope},
        ),
        inputs_summary=fingerprint.inputs_summary,
    ).to_dict())

    with _ipc_owner(tmp_path, monkeypatch, (resident.launch_profile,)) as (client, owner, _dispatch):
        launch = _retain_shared_launch(client, tmp_path, resident, request)
        workspace = _ResidentAssignmentWorkspace(tmp_path / "agent", request.assignment_id)
        workspace.persist_supervisor_launch(json.dumps(_launch_value(launch)))
        started = client.launch(launch)
        assert started.started
        workspace.mark_process_started(launch.process_execution_id, started.process_id)
        deadline = monotonic() + 120
        result_path = workspace.root / "worker-result.json"
        while not result_path.is_file():
            assert monotonic() < deadline, "installed worker produced no result"
            sleep(0.05)
        receipt = client.query_wait(launch)
        while receipt.state in {SupervisorLaunchState.STARTING, SupervisorLaunchState.RUNNING}:
            assert monotonic() < deadline, "installed worker did not exit"
            sleep(0.05)
            receipt = client.query_wait(launch)
        assert receipt.state is SupervisorLaunchState.EXITED
        assert receipt.exit_code == 0
        original_identity = launch.spec_digest
        unavailable = tmp_path / "unavailable-input"
        data.rename(unavailable)
        walk = os.walk

        def forbid_input_walk(top, *args, **kwargs):
            path = Path(top)
            assert not path.is_relative_to(data) and not path.is_relative_to(unavailable), (
                "completed observation/publication must not traverse inputs"
            )
            return walk(top, *args, **kwargs)

        monkeypatch.setattr(os, "walk", forbid_input_walk)
        terminal = client.contain(launch)
        assert terminal.state is SupervisorLaunchState.CONTAINED
        assert terminal.successful_exit
        assert terminal.worker_result_digest == hashlib.sha256(result_path.read_bytes()).hexdigest()
        workspace.persist_worker_result(StageWorkerResult.from_dict(json.loads(result_path.read_text())))
        report = workspace.retain_outputs()
        assert report.status is StageStatus.SUCCEEDED
        assert launch.spec_digest == original_identity
        published = publish(request, report, roots, agent_id=launch.agent_id, fence=launch.execution_fence)
        assert uri_to_path(published["result"].uri).read_bytes() == b"qualified synthetic output"
        assert publish(request, report, roots, agent_id=launch.agent_id, fence=launch.execution_fence) == published
        counters = list(workspace.root.rglob("executions.txt"))
        assert len(counters) == 1 and counters[0].read_text() == "execution\n"
        with owner._connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 1
        assert owner.quiescent()
