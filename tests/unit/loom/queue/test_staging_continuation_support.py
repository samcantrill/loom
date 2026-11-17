"""Continuation admission covers native sessions and selected installations."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from loom.pipeline.planning import StageFingerprintRecord
from loom.pipeline.specs import OutputSpec, StageFactorySpec, StageSpec
from loom.queue import resident_readiness
from loom.queue.agent_sessions import _require_target_session
from loom.queue.errors import QueueServiceError
from loom.queue.local_daemon_runtime import _preparation_constraints
from loom.queue.preparation import PREPARATION_STAGE_TARGET, PreparationChildInput, SharedInputReceipt
from loom.queue.shared_execution import (
    SHARED_EXECUTION_CAPABILITY, SHARED_EXECUTION_SCOPE, STAGING_CONTINUATION_CAPABILITY,
    assignment_requires_staging_continuation, assignment_scope, attributes,
)
from loom.scheduling import AttributeConstraintEvaluator, Candidate
from tests.unit.loom.queue.test_shared_recovery import _workspace
from tests.unit.loom.queue.test_staging_continuation_grants import _client, _select


def _preparation_fingerprint(request, profile):
    record = StageFingerprintRecord.from_dict(request.fingerprint)
    binding = PreparationChildInput(
        "operation", "profile", "pipeline.yaml",
        SharedInputReceipt("sha256:" + "a" * 64, "projects", "capture"),
        profile.descriptor.to_dict(), shared_scope=assignment_scope(request.fingerprint),
        staging_continuation_stages=("predict",),
    )
    return StageFingerprintRecord.create(
        algorithm=record.algorithm, inputs_summary=record.inputs_summary,
        payload=replace(record.payload, factory_target=PREPARATION_STAGE_TARGET, stage_config=binding.to_dict()),
    ).to_dict()


@pytest.mark.parametrize("preparation", [False, True])
def test_stage_constraints_require_support_for_downstream_continuation(tmp_path, preparation):
    workspace, profile, _ = _workspace(tmp_path)
    ordinary = workspace.request()
    fingerprint = (_preparation_fingerprint(ordinary, profile) if preparation
                   else _select(ordinary).fingerprint)
    assert assignment_requires_staging_continuation(fingerprint)
    assert not assignment_requires_staging_continuation(ordinary.fingerprint)
    payload = StageFingerprintRecord.from_dict(fingerprint).payload
    stage = StageSpec("build", StageFactorySpec(payload.factory_target),
                      {"result": OutputSpec("bytes", "bytes.v1")},
                      stage_config=payload.stage_config, fingerprint_fields=payload.fingerprint_fields)
    evaluator = AttributeConstraintEvaluator()
    required = _preparation_constraints(stage, {"attribute": evaluator})[0]
    assert required.data["attributes"]["staging_continuation_capability"] == STAGING_CONTINUATION_CAPABILITY
    candidate_attributes = attributes(assignment_scope(ordinary.fingerprint))
    candidate = Candidate("native", {}, {}, attributes=candidate_attributes)
    assert evaluator.evaluate(None, candidate, (), required).state.value == "reject"
    candidate = replace(candidate, attributes={**candidate_attributes,
        "staging_continuation_capability": STAGING_CONTINUATION_CAPABILITY})
    assert evaluator.evaluate(None, candidate, (), required).state.value == "pass"
    if preparation:
        assert "staging_continuation" not in payload.fingerprint_fields[SHARED_EXECUTION_SCOPE]


def test_targeted_delivery_rejects_missing_negotiated_native_capability(tmp_path):
    workspace, profile, _ = _workspace(tmp_path)
    request = _select(workspace.request())
    control = _client(tmp_path, request, profile, "resident").control
    daemon = SimpleNamespace(_epoch="epoch", _require_started=lambda: "coordinator")
    with control.connection() as conn:
        conn.execute("UPDATE agent_sessions SET capabilities_json=?", (json.dumps([SHARED_EXECUTION_CAPABILITY]),))
        with pytest.raises(QueueServiceError, match="agent session lacks released-output-staging-v1"):
            _require_target_session(daemon, conn, "session-1", request)
        _require_target_session(daemon, conn, "session-1", workspace.request())
        conn.execute("UPDATE agent_sessions SET capabilities_json=?", (
            json.dumps([SHARED_EXECUTION_CAPABILITY, STAGING_CONTINUATION_CAPABILITY]),
        ))
        assert STAGING_CONTINUATION_CAPABILITY in _require_target_session(daemon, conn, "session-1", request).capabilities


def test_resident_candidates_and_slurm_submit_selection_follow_negotiated_support(tmp_path):
    from loom.queue._shared_assignment import CAPABILITY
    from loom.queue.local_daemon_execution import LocalDaemonExecution
    from loom.pipeline.executors.slurm.errors import SlurmPlanningError
    from tests.unit.loom.queue.test_agent_sessions import _offer, _policy

    workspace, profile, _ = _workspace(tmp_path)
    root = {key: value for key, value in profile.shared_roots["outputs"].items() if key != "publication"}
    profile = replace(profile, shared_roots={**profile.shared_roots, "control": {**root, "container_path": None}})
    control = _client(tmp_path, _select(workspace.request()), profile, "resident").control
    pair = ("slurm", "a" * 64)
    policy = _policy()
    policy = replace(policy, agents=(replace(policy.agents[0], external_slurm_profiles=(pair,)),))
    offer = replace(_offer("session-1", "epoch"), resident_profiles=(profile.descriptor,), external_slurm_profiles=(pair,))
    with control.connection() as conn:
        conn.execute("UPDATE remote_assignments SET state='RELEASED'")
        conn.execute("INSERT INTO agent_offers VALUES (?,?,?,?,?,?,?,?)", (
            "offer", "session-1", "epoch", "availability-1", json.dumps(offer.value()),
            "2020-01-01T00:00:00Z", "2999-01-01T00:00:00Z", 1,
        ))
    config = SimpleNamespace(
        remote_profiles=(profile.descriptor,), container_capabilities=(),
        control_database=control.path, connect_database=lambda path: control.connection(),
        agent_policy=policy, assignment_payload_root_id="control", coordinator_shared_roots=profile.shared_roots,
    )
    execution = object.__new__(LocalDaemonExecution)
    execution.config = config
    execution.daemon = SimpleNamespace(config=config, _agent_policy=policy,
                                        _accepted_snapshot=lambda: ("2020-01-01T00:00:00Z", 0))
    execution.coordinator_epoch = "epoch"
    execution.agent_id = None
    execution._slurm_agent = None
    slurm = SimpleNamespace(profile_id=pair[0], configuration_fingerprint=pair[1])
    for capable in (False, True):
        capabilities = [SHARED_EXECUTION_CAPABILITY, CAPABILITY]
        if capable:
            capabilities.append(STAGING_CONTINUATION_CAPABILITY)
        with control.connection() as conn:
            conn.execute("UPDATE agent_sessions SET capabilities_json=?", (json.dumps(capabilities),))
        ((candidate, _),) = execution._remote_candidates().values()
        assert ("staging_continuation_capability" in candidate.attributes) is capable
        assert execution._select_slurm_agent(slurm) == ("agent-a", "agent-1")
        if capable:
            assert execution._select_slurm_agent(slurm, require_continuation=True) == ("agent-a", "agent-1")
        else:
            with pytest.raises(SlurmPlanningError, match="slurm_profile_unavailable"):
                execution._select_slurm_agent(slurm, require_continuation=True)


def test_registration_checks_coordinator_before_persisting_continuation_intent():
    from loom.queue._agent_session_protocol import register
    from loom.queue.agent_sessions import AgentRegistration, SLURM_SUBMISSION_CAPABILITY

    client = SimpleNamespace(
        _config=SimpleNamespace(agent_root=None, container_policies=()),
        handshake=lambda: {"capabilities": []},
        _require_journal=lambda: pytest.fail("unsupported registration was persisted"),
    )
    request = AgentRegistration("register", "coordinator", "epoch", "root", "config", "inventory", "available",
                                ("default",), (STAGING_CONTINUATION_CAPABILITY, SLURM_SUBMISSION_CAPABILITY))
    with pytest.raises(QueueServiceError, match="coordinator lacks released-output-staging-v1"):
        next(register(client, request))


@pytest.mark.parametrize("preparation", [False, True])
def test_real_selected_python_probe_accepts_current_and_refuses_older_contracts(tmp_path, preparation):
    workspace, profile, _ = _workspace(tmp_path)
    fingerprint = (_preparation_fingerprint(workspace.request(), profile) if preparation
                   else _select(workspace.request()).fingerprint)
    current = replace(profile.launch_profile, environment={"PYTHONPATH": str(Path.cwd() / "src")})
    resident_readiness.require_staging_continuation_support(current, fingerprint)
    old = tmp_path / "old-installation"
    queue = old / "loom/queue"
    queue.mkdir(parents=True)
    (old / "loom/__init__.py").write_text("")
    (queue / "__init__.py").write_text("")
    # A storage primitive's token alone cannot qualify the later consumers.
    (queue / "shared_execution.py").write_text(
        'STAGING_CONTINUATION_CAPABILITY = "released-output-staging-v1"\n'
    )
    unsupported = replace(current, environment={"PYTHONPATH": str(old)})
    with pytest.raises(QueueServiceError, match="selected worker lacks released-output-staging-v1 qualification"):
        resident_readiness.require_staging_continuation_support(unsupported, fingerprint)
    # The opt-in must not reject an old installation for ordinary work.
    resident_readiness.require_staging_continuation_support(unsupported, workspace.request().fingerprint)


def test_qualification_executes_in_selected_container_environment(tmp_path):
    from examples.execution.containers.apptainer_fixture import fake_apptainer

    workspace, profile, _ = _workspace(tmp_path)
    fingerprint = _select(workspace.request()).fingerprint
    with fake_apptainer() as binding:
        # Shared containers discard host PYTHONPATH. This foreground fixture
        # models the image's installed source path using its synthetic contents.
        command = Path(binding["options"]["command"])
        command.write_text(command.read_text().replace(
            "args.pop(0)\nos.execvpe", "os.environ['PYTHONPATH'] = open(args.pop(0)).read()\nos.execvpe",
        ))
        image = Path(binding["container"]["image"]["reference"])
        image.write_text(str(Path.cwd() / "src"))
        current = replace(profile.launch_profile, container=binding,
                          environment={"PYTHONPATH": str(Path.cwd() / "src")})
        resident_readiness.require_staging_continuation_support(current, fingerprint)
        old = tmp_path / "old-image/loom"
        old.mkdir(parents=True)
        (old / "__init__.py").write_text("")
        image.write_text(str(old.parent))
        with pytest.raises(QueueServiceError, match="selected worker lacks released-output-staging-v1 qualification"):
            resident_readiness.require_staging_continuation_support(current, fingerprint)


def test_submitted_continuation_launch_verifies_image_once(tmp_path, monkeypatch):
    from examples.execution.containers.apptainer_fixture import fake_apptainer
    from loom.queue._container_worker import qualify_shared_worker_inputs
    from loom.queue._submitted_container_policy import SubmittedContainerPolicy
    from loom.queue import submitted_execution as submitted

    workspace, installed, _ = _workspace(tmp_path)
    images = tmp_path / "images"
    images.mkdir()
    (images / "challenge").write_bytes(b"images")
    image = images / "fixture.sif"
    image.write_text(str(Path.cwd() / "src"))
    image.chmod(0o444)
    roots = {**installed.shared_roots, "images": {
        "host_path": str(images), "container_path": None, "access": "ro",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"images").hexdigest()},
    }}
    with fake_apptainer() as runtime:
        command = Path(runtime["options"]["command"])
        command.write_text(command.read_text().replace(
            "args.pop(0)\nos.execvpe", "os.environ['PYTHONPATH'] = open(args.pop(0)).read()\nos.execvpe",
        ))
        policy = SubmittedContainerPolicy("images", runtime["options"], roots, ("images",))
        execution = submitted.SubmittedContainerExecution(
            "apptainer", submitted.SubmittedImage(
                {"kind": "loom.shared-location", "schema_version": 1, "root_id": "images", "path": "fixture.sif"},
                hashlib.sha256(image.read_bytes()).hexdigest(), image.stat().st_size,
            ), sys.executable, submitted.SUBMITTED_CONTAINER_WORKER_CONTRACT,
        )
        request = _select(workspace.request())
        record = StageFingerprintRecord.from_dict(request.fingerprint)
        request = replace(request, profile=policy.capability, fingerprint=StageFingerprintRecord.create(
            algorithm=record.algorithm, inputs_summary=record.inputs_summary,
            payload=replace(record.payload, fingerprint_fields={**record.payload.fingerprint_fields,
                submitted.SUBMITTED_EXECUTION_SCOPE: {
                    "execution": execution.to_dict(), "container_capability": policy.capability.to_dict(),
                },
            }),
        ).to_dict(), worker_metadata={**request.worker_metadata, "loom.execution_binding": {
            **request.worker_metadata["loom.execution_binding"],
            "environment_fingerprint": policy.capability.environment_fingerprint,
        }})
        profile = policy.launch_profile(execution, workspace=workspace.root)
        audited = []
        verify = submitted.verify_submitted_image

        def observe(image, roots):
            audited.append(image.sha256)
            return verify(image, roots)

        monkeypatch.setattr(submitted, "verify_submitted_image", observe)
        qualify_shared_worker_inputs(profile, request, agent_id="agent-1")
        assert audited == [execution.image.sha256]


@pytest.mark.parametrize("contained,failure", [(False, None), (True, "resident probe timed out")])
def test_probe_requires_containment_and_success_even_with_positive_payload(tmp_path, monkeypatch, contained, failure):
    from loom.queue._resident_probe import ResidentProbeResult

    workspace, profile, _ = _workspace(tmp_path)
    monkeypatch.setattr(resident_readiness, "run_resident_probe", lambda *args, **kwargs: ResidentProbeResult(
        {"capability": STAGING_CONTINUATION_CAPABILITY, "available": True}, failure, contained,
    ))
    with pytest.raises(QueueServiceError, match="qualification"):
        resident_readiness.require_staging_continuation_support(profile.launch_profile, _select(workspace.request()).fingerprint)


def test_new_shared_launch_checks_support_but_unselected_launch_never_probes(tmp_path, monkeypatch):
    from loom.queue._container_worker import qualify_shared_worker_inputs

    workspace, profile, _ = _workspace(tmp_path)
    request = _select(workspace.request())
    called = []

    def unavailable(*args, **kwargs):
        called.append(True)
        raise QueueServiceError("selected installation unavailable")

    monkeypatch.setattr(resident_readiness, "run_resident_probe", unavailable)
    qualify_shared_worker_inputs(profile.launch_profile, workspace.request(), agent_id="agent-1")
    assert called == []
    with pytest.raises(QueueServiceError, match="selected installation unavailable"):
        qualify_shared_worker_inputs(profile.launch_profile, request, agent_id="agent-1")
    assert called == [True]
