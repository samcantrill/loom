from __future__ import annotations

import json
from pathlib import Path

import pytest

from loom.queue.errors import QueueServiceError
from loom.queue.slurm_bootstrap import SlurmBootstrapClientConfig


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
