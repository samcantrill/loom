from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.queue.errors import QueueServiceError
from loom.queue.slurm_bootstrap import (
    SlurmBootstrapClientConfig,
    _read_job_private_capability,
    _unlink_job_private_capability,
    run_slurm_bootstrap,
)
import loom.queue.slurm_bootstrap as slurm_bootstrap
from loom.pipeline import ProcessContainmentOwner
from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace
from loom.serialization import freeze_plain_data


def test_fixed_bootstrap_cli_loads_explicit_private_configuration(tmp_path, monkeypatch):
    import argparse
    from loom.cli.slurm_bootstrap import register_subparser

    parser = argparse.ArgumentParser()
    register_subparser(parser.add_subparsers())
    path = tmp_path / "bootstrap.json"
    path.write_text(json.dumps(_config_value(tmp_path)))
    path.chmod(0o600)
    observed = []
    monkeypatch.setattr(slurm_bootstrap, "run_slurm_bootstrap", lambda **kwargs: observed.append(kwargs))
    arguments = parser.parse_args(["slurm-bootstrap", "--config", str(path),
                                   "--operation-id", "operation", "--request-digest", "digest"])
    assert arguments.handler(arguments) == 0
    assert observed[0]["config"].profile_id == "training"
    assert observed[0]["operation_id"] == "operation"


def _config_value(tmp_path: Path) -> dict[str, str]:
    project = tmp_path / "project"
    project.mkdir()
    return {
        "url": "https://coordinator.example",
        "server_ca_path": str(tmp_path / "ca.pem"),
        "certificate_path": str(tmp_path / "bootstrap.pem"),
        "private_key_path": str(tmp_path / "bootstrap.key"),
        "workspace_root": str(tmp_path / "workspace"),
        "project_root": str(project),
        "profile_id": "training",
        "profile_configuration_fingerprint": "profile-v1",
        "credential_policy_revision": "slurm-policy-1",
        "project_fingerprint": "project-v1",
        "environment_fingerprint": "environment-v1",
        "executor_fingerprint": "executor-v1",
        "executor_name": "local",
        "capability_file_path": str(tmp_path / "job-private-capability"),
    }


def test_bootstrap_config_is_private_and_pins_profile_policy(tmp_path: Path) -> None:
    path = tmp_path / "bootstrap.json"
    path.write_text(json.dumps(_config_value(tmp_path)), encoding="utf-8")
    path.chmod(0o600)

    config = SlurmBootstrapClientConfig.from_file(path)

    assert config.profile_id == "training"
    assert config.profile_configuration_fingerprint == "profile-v1"
    assert config.credential_policy_revision == "slurm-policy-1"
    assert not config.workspace_root.exists()
    config.qualify()
    assert config.workspace_root.is_dir()
    assert config.workspace_root.stat().st_mode & 0o077 == 0

    path.chmod(0o644)
    with pytest.raises(QueueServiceError, match="private file"):
        SlurmBootstrapClientConfig.from_file(path)


def test_bootstrap_config_rejects_the_pre_policy_shape(tmp_path: Path) -> None:
    value = _config_value(tmp_path)
    del value["credential_policy_revision"]
    path = tmp_path / "bootstrap.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(QueueServiceError, match="fields are invalid"):
        SlurmBootstrapClientConfig.from_file(path)


@pytest.mark.parametrize("invalid", [None, "mixed", "unversioned", "version", "kind", "durability"])
def test_tagged_trusted_user_bootstrap_is_explicit_and_side_effect_free(tmp_path, invalid):
    value = _config_value(tmp_path)
    value.pop("capability_file_path")
    value.update(schema_version=1, credential_delivery={
        "kind": "user_private_file_v1", "root": str(tmp_path / "credentials"),
        "descriptor": "trusted-test-v1",
    })
    if invalid == "mixed":
        value["capability_file_path"] = str(tmp_path / "fixed")
    elif invalid == "unversioned":
        value.pop("schema_version")
    elif invalid == "version":
        value["schema_version"] = 2
    elif invalid == "kind":
        value["credential_delivery"]["kind"] = "unknown"
    elif invalid == "durability":
        value["durable_files"] = "best_effort"
    path = tmp_path / "bootstrap.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    if invalid is None:
        loaded = SlurmBootstrapClientConfig.from_file(path)
        assert loaded.capability_file_path is None
        assert loaded.durable_files == "strict"
        assert loaded.credential_delivery == value["credential_delivery"]
    else:
        with pytest.raises(QueueServiceError):
            SlurmBootstrapClientConfig.from_file(path)
    assert not (tmp_path / "credentials").exists()
    assert not (tmp_path / "workspace").exists()


def test_job_private_capability_is_regular_bounded_and_unlinked(tmp_path: Path) -> None:
    path = tmp_path / "capability"
    secret = b"a" * 32
    path.write_bytes(secret)
    path.chmod(0o600)

    assert _read_job_private_capability(path) == secret
    _unlink_job_private_capability(path)
    assert not path.exists()

    target = tmp_path / "target"
    target.write_bytes(secret)
    (tmp_path / "link").symlink_to(target)
    with pytest.raises(QueueServiceError, match="regular file"):
        _read_job_private_capability(tmp_path / "link")


@pytest.mark.parametrize("pending_responses", [0, 2, None])
@pytest.mark.parametrize(("durable_files", "trusted_user"), [("best_effort", False), ("strict", False), ("strict", True)])
def test_bootstrap_passes_outer_boundary_containment_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pending_responses: int | None,
    durable_files: str, trusted_user: bool,
) -> None:
    config_path = tmp_path / "bootstrap.json"
    config_value = _config_value(tmp_path)
    if trusted_user:
        from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider

        provider = SlurmUserPrivateFileProvider(root=tmp_path / "credentials", descriptor="trusted-test-v1")
        prepared = provider.prepare(operation_id="operation-1", request_digest="digest-1")
        expected_token = provider.read_capability(operation_id="operation-1", request_digest="digest-1")
        config_value.pop("capability_file_path")
        config_value.update(schema_version=1, credential_delivery={
            "kind": provider.delivery_kind, "root": str(provider.root), "descriptor": provider.descriptor,
        })
    config_path.write_text(json.dumps(config_value), encoding="utf-8")
    config_path.chmod(0o600)
    config = SlurmBootstrapClientConfig.from_file(config_path)
    config = replace(config, bootstrap_deadline_seconds=3, reconnect_seconds=1, durable_files=durable_files)
    captured: dict[str, object] = {}
    actions: list[str] = []
    now = [10.0]
    monkeypatch.setattr(slurm_bootstrap.time, "time", lambda: now[0])
    monkeypatch.setattr(
        slurm_bootstrap.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay)
    )

    class FakeClient:
        def handshake(self, *, role: str) -> dict[str, object]:
            assert role == "slurm_bootstrap"
            return {
                "capabilities": ["slurm-ready-stage-bootstrap-v1"],
                "profile_id": "training",
                "profile_descriptor": {},
                "credential_policy_revision": "slurm-policy-1",
            }

        def call_application(
            self, role: str, action: str, payload: dict[str, object]
        ) -> dict[str, object]:
            assert role == "slurm_bootstrap"
            actions.append(action)
            if action == "inputs_ready":
                if (
                    pending_responses is None
                    or actions.count(action) <= pending_responses
                ):
                    return {"state": "awaiting_submission_ack"}
                return {"state": "input_ready"}
            if action == "register":
                if trusted_user:
                    import base64
                    assert base64.b64decode(payload["capability"]) == expected_token
                return freeze_plain_data({
                    "assignment_id": "assignment-1",
                    "delivery": {"nested": {"sequence": [1, 2]}},
                    "result_identity": {"assignment": {"assignment_id": "assignment-1"}},
                })
            if action == "grant":
                return {"fence": "fence-1"}
            if action == "start":
                return {"permitted": True}
            return {}

        def close(self) -> None:
            pass

    class FakeWorkspace:
        def __init__(self, _root: Path, _assignment_id: str, **kwargs) -> None:
            assert kwargs == {"durable_files": durable_files}
            self.root = tmp_path / "resident-workspace"
            self.root.mkdir()

        def persist_registration(self, registration: object) -> None:
            retained = SlurmBootstrapWorkspace(
                tmp_path / "protocol", "assignment-1", durable_files=durable_files,
            )
            retained.persist_registration(registration)
            # Reopen and repeat the exact response, as after a lost acknowledgement.
            SlurmBootstrapWorkspace(
                tmp_path / "protocol", "assignment-1", durable_files=durable_files,
            ).persist_registration(registration)
            assert json.loads((retained.root / "registration.json").read_text())["delivery"] == {
                "nested": {"sequence": [1, 2]},
            }

        def persist_delivery(self, _delivery: object) -> None:
            pass

        def accept_inputs(self) -> None:
            pass

        def worker_request(self) -> object:
            return object()

        def retain_result(self, _result: object) -> SimpleNamespace:
            return SimpleNamespace(to_dict=lambda: {}, outputs=())

    monkeypatch.setenv("SLURM_JOB_ID", "123")
    monkeypatch.setattr(slurm_bootstrap.os, "chdir", lambda _path: None)
    monkeypatch.setattr(slurm_bootstrap.sys, "path", list(slurm_bootstrap.sys.path))
    monkeypatch.setattr(
        slurm_bootstrap, "LocalDaemonAgentHttpClient", lambda _tls: FakeClient()
    )
    monkeypatch.setattr(
        slurm_bootstrap.SchedulingComponentDescriptor,
        "from_dict",
        lambda _value: SimpleNamespace(configuration_fingerprint="profile-v1"),
    )
    monkeypatch.setattr(
        slurm_bootstrap, "_read_job_private_capability", lambda _path: b"capability"
    )
    if not trusted_user:
        monkeypatch.setattr(
            slurm_bootstrap, "_unlink_job_private_capability", lambda _path, **_kwargs: None
        )
    monkeypatch.setattr(
        slurm_bootstrap.SlurmStageDelivery,
        "from_dict",
        lambda _value: SimpleNamespace(
            assignment_id="assignment-1",
            profile_id="training",
            project_fingerprint="project-v1",
            environment_fingerprint="environment-v1",
            executor_fingerprint="executor-v1",
            executor_name="local",
            submitted_execution=None,
            inputs=(),
        ),
    )
    def publish(identity, _report, _output):
        # The shared result journal also writes the nested identity as JSON.
        assert json.loads(json.dumps(identity)) == {
            "assignment": {"assignment_id": "assignment-1"}, "fence": "fence-1",
        }
        actions.append("publish")

    monkeypatch.setattr(
        slurm_bootstrap,
        "SharedSlurmResult",
        lambda *_args, **_kwargs: SimpleNamespace(
            publish=publish
        ),
    )
    monkeypatch.setattr(
        FakeWorkspace, "output_chunk", lambda *_args: (b"", True), raising=False
    )
    monkeypatch.setattr(slurm_bootstrap, "SlurmBootstrapWorkspace", FakeWorkspace)
    monkeypatch.setattr(
        slurm_bootstrap,
        "execute_resident_stage_worker_request",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    if pending_responses is None:
        with pytest.raises(
            QueueServiceError, match="deadline expired; no offline grant"
        ):
            run_slurm_bootstrap(
                operation_id="operation-1", request_digest="digest-1", config=config
            )
        assert actions == ["register", "inputs_ready", "inputs_ready", "inputs_ready"]
        assert captured == {}
        (diagnostic,) = config.workspace_root.glob("bootstrap-failure-*.json")
        assert json.loads(diagnostic.read_text())["offline_grant"] is False
    else:
        run_slurm_bootstrap(
            operation_id="operation-1", request_digest="digest-1", config=config
        )
        assert actions[: pending_responses + 4] == [
            "register",
            *(["inputs_ready"] * (pending_responses + 1)),
            "grant",
            "start",
        ]
        assert (
            captured["process_containment_owner"]
            is ProcessContainmentOwner.OUTER_BOUNDARY
        )
    if trusted_user:
        assert not Path(prepared.path).exists()
        assert provider.prepare(operation_id="operation-1", request_digest="digest-1") == prepared
        assert not Path(prepared.path).exists()


def test_strict_incarnation_replay_after_failed_publication_sync(tmp_path, monkeypatch):
    import loom.pipeline.stores.atomic as atomic

    root = tmp_path / "workspace"
    root.mkdir()
    sync = atomic._fsync_path_strict
    failed = False

    def fail_after_publish(path):
        nonlocal failed
        if (path / "incarnation").exists() and not failed:
            failed = True
            raise OSError("injected directory sync failure")
        sync(path)

    monkeypatch.setattr(atomic, "_fsync_path_strict", fail_after_publish)
    with pytest.raises(atomic.AtomicWriteError, match="sync failure"):
        slurm_bootstrap._operation_incarnation(root, "operation", durable_files="strict")
    assert failed
    retained = next(root.glob("operations/*/incarnation")).read_text().strip()
    assert slurm_bootstrap._operation_incarnation(root, "operation", durable_files="strict") == retained


def test_strict_bootstrap_fsync_failure_prevents_any_remote_start(tmp_path, monkeypatch):
    import loom.pipeline.stores.atomic as atomic

    path = tmp_path / "bootstrap.json"
    value = _config_value(tmp_path)
    value["durable_files"] = "strict"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    config = SlurmBootstrapClientConfig.from_file(path)
    monkeypatch.setenv("SLURM_JOB_ID", "123")
    monkeypatch.setattr(slurm_bootstrap, "LocalDaemonAgentHttpClient", lambda *_: pytest.fail("connected before durable bootstrap state"))
    monkeypatch.setattr(atomic.os, "fsync", lambda *_: (_ for _ in ()).throw(OSError("unavailable sync")))
    with pytest.raises(atomic.AtomicWriteError, match="unavailable sync"):
        run_slurm_bootstrap(operation_id="operation", request_digest="request", config=config)


def test_prestart_reconnect_deadline_never_grants_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loom.queue.agent_session_transport import _IndeterminateAgentProtocolError

    now = [10.0]
    calls = []
    monkeypatch.setattr(slurm_bootstrap.time, "time", lambda: now[0])
    monkeypatch.setattr(
        slurm_bootstrap.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay)
    )

    def disconnected():
        calls.append(now[0])
        raise _IndeterminateAgentProtocolError("coordinator unavailable")

    diagnostic = tmp_path / "failure.json"
    with pytest.raises(QueueServiceError, match="no offline grant"):
        slurm_bootstrap._before_start_retry(
            disconnected, deadline=12, delay=1, diagnostic=diagnostic
        )
    assert calls == [10, 11]
    assert json.loads(diagnostic.read_text())["offline_grant"] is False
    with pytest.raises(QueueServiceError, match="deadline expired"):
        slurm_bootstrap._before_start_retry(
            lambda: {"fence": "must-not-be-used"},
            deadline=12,
            delay=1,
            diagnostic=diagnostic,
        )
