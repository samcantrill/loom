from __future__ import annotations

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


def test_bootstrap_passes_outer_boundary_containment_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "bootstrap.json"
    config_path.write_text(json.dumps(_config_value(tmp_path)), encoding="utf-8")
    config_path.chmod(0o600)
    config = SlurmBootstrapClientConfig.from_file(config_path)
    captured: dict[str, object] = {}

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
            if action == "register":
                return {"assignment_id": "assignment-1", "delivery": {}}
            if action == "grant":
                return {"fence": "fence-1"}
            if action == "start":
                return {"permitted": True}
            return {}

        def close(self) -> None:
            pass

    class FakeWorkspace:
        def __init__(self, _root: Path, _assignment_id: str) -> None:
            self.root = tmp_path / "resident-workspace"
            self.root.mkdir()

        def persist_registration(self, _registration: object) -> None:
            pass

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
    monkeypatch.setattr(
        slurm_bootstrap, "_unlink_job_private_capability", lambda _path: None
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
            inputs=(),
        ),
    )
    monkeypatch.setattr(slurm_bootstrap, "SlurmBootstrapWorkspace", FakeWorkspace)
    monkeypatch.setattr(
        slurm_bootstrap,
        "execute_resident_stage_worker_request",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    run_slurm_bootstrap(
        operation_id="operation-1", request_digest="digest-1", config=config
    )

    assert (
        captured["process_containment_owner"] is ProcessContainmentOwner.OUTER_BOUNDARY
    )


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
