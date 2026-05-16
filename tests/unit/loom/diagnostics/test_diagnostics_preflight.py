"""Unit tests for the local preflight runner."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sys
from types import ModuleType
from typing import Any, cast

import pytest

from loom.diagnostics import (
    PreflightCheckStatus,
    PreflightRequest,
    PreflightStatus,
    run_preflight,
)
from loom.diagnostics.models import PreflightError
from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
    path_to_run_uri,
)


pytestmark = pytest.mark.unit


def test_selected_codec_group_runs_only_codec_check() -> None:
    result = run_preflight(
        PreflightRequest(config_path="missing.yaml", groups=("codecs",))
    )

    assert result.status is PreflightStatus.PASS
    assert result.groups[0].value == "codecs"
    assert [check.check_id for check in result.checks] == ["codec_registry.available"]


def test_missing_run_uri_skips_run_path_dependent_groups() -> None:
    result = run_preflight(
        PreflightRequest(config_path="missing.yaml", groups=("run", "artifacts"))
    )

    assert result.status is PreflightStatus.SKIP
    assert all(check.status is PreflightCheckStatus.SKIP for check in result.checks)
    assert [check.details["reason"] for check in result.checks] == [
        "missing_run_uri",
        "missing_run_uri",
        "no_artifact_backend_targets",
        "no_artifact_backend_targets",
        "no_artifact_backend_targets",
        "no_artifact_backend_targets",
    ]


def test_run_uri_group_uses_explicit_runtime_run_uri_without_config(
    tmp_path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "runs" / "demo")

    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("run",),
            runtime_options={"run_uri": run_uri},
        )
    )

    assert result.status is PreflightStatus.PASS
    assert result.checks[0].check_id == "run_uri.resolve"
    assert result.checks[0].details["run_uri"] == run_uri
    source = cast(dict[str, Any], result.checks[0].details["state_source"])
    authority_policy = cast(
        dict[str, Any], result.checks[0].details["authority_policy"]
    )
    policy_source = cast(dict[str, Any], authority_policy["source"])
    assert source["label"] == "materialized_local_state"
    assert policy_source["label"] == "authoritative_service_truth"


def test_run_uri_group_labels_offline_first_authority_policy_source(tmp_path) -> None:
    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("run",),
            runtime_options={
                "run_uri": path_to_run_uri(tmp_path / "runs" / "offline-demo")
            },
            authority_mode="offline_first",
        )
    )

    authority_policy = cast(
        dict[str, Any], result.checks[0].details["authority_policy"]
    )
    policy_source = cast(dict[str, Any], authority_policy["source"])
    assert policy_source["label"] == "offline_evidence"
    assert policy_source["policy"] == "offline_first"
    assert policy_source["authoritative"] is False


def test_run_uri_group_labels_deferred_finalization_policy_source(tmp_path) -> None:
    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("run",),
            runtime_options={
                "run_uri": path_to_run_uri(tmp_path / "runs" / "deferred-demo")
            },
            authority_config=AuthorityConfig(
                backend_kind=AuthorityBackendKind.DEFERRED_FINALIZATION,
                deployment_profile=AuthorityDeploymentProfile.DEFERRED_FINALIZATION,
            ),
        )
    )

    authority_policy = cast(
        dict[str, Any], result.checks[0].details["authority_policy"]
    )
    policy_source = cast(dict[str, Any], authority_policy["source"])
    assert policy_source["label"] == "deferred_finalization_state"
    assert policy_source["policy"] == "deferred_finalization"
    assert policy_source["authoritative"] is False


def test_run_uri_group_does_not_compose_config_for_non_uri_runtime_flags() -> None:
    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("run",),
            runtime_options={"executor": "local"},
        )
    )

    assert result.status is PreflightStatus.SKIP
    assert result.checks[0].details["reason"] == "missing_run_uri"


def test_empty_selected_groups_are_request_errors() -> None:
    with pytest.raises(PreflightError, match="empty"):
        run_preflight(PreflightRequest(config_path="config.yaml", groups=()))


def test_unknown_selected_groups_are_request_errors() -> None:
    with pytest.raises(PreflightError, match="unknown preflight group"):
        run_preflight(PreflightRequest(config_path="config.yaml", groups=("nope",)))


def test_filesystem_check_reports_missing_inputs(tmp_path) -> None:
    result = run_preflight(
        PreflightRequest(
            config_path=tmp_path / "missing.yaml",
            groups=("filesystem",),
            overlays=(tmp_path / "overlay.yaml",),
        )
    )

    assert result.status is PreflightStatus.FAIL
    check = result.checks[0]
    assert check.check_id == "filesystem.input_exists"
    assert check.details["missing"] == [
        str(tmp_path / "missing.yaml"),
        str(tmp_path / "overlay.yaml"),
    ]


def test_runtime_executor_and_resource_checks_map_capability_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime_preflight_dependencies(monkeypatch)

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("runtime", "executor", "resources"),
            runtime_options={
                "executor": "local",
                "adapter_options": {"future": {"enabled": True}},
                "stage_options": {
                    "train": {
                        "resources": {"entries": {"cpu": {"kind": "cpu", "amount": 2}}}
                    }
                },
            },
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.WARN
    assert by_id["runtime.options"].status is PreflightCheckStatus.PASS
    assert by_id["runtime.stage_options"].status is PreflightCheckStatus.PASS
    assert by_id["executor.resolve"].status is PreflightCheckStatus.PASS
    assert by_id["executor.capabilities"].status is PreflightCheckStatus.WARN
    executor_diagnostics = cast(
        list[dict[str, Any]],
        by_id["executor.capabilities"].details["diagnostics"],
    )
    assert executor_diagnostics[0]["code"] == "adapter_namespace.unclaimed"
    assert by_id["resources.capabilities"].status is PreflightCheckStatus.WARN
    resource_diagnostics = cast(
        list[dict[str, Any]],
        by_id["resources.capabilities"].details["diagnostics"],
    )
    assert resource_diagnostics[0]["code"] == "resource.ignored"


def test_executor_preflight_reports_reliability_policy_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime_preflight_dependencies(monkeypatch)

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor",),
            runtime_options={
                "executor": "local",
                "reliability": {
                    "retry": {"enabled": True, "max_attempts": 2},
                    "timeout": {"enabled": True, "duration_seconds": 3},
                },
            },
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    diagnostics = cast(
        list[dict[str, Any]],
        by_id["executor.capabilities"].details["diagnostics"],
    )
    assert result.status is PreflightStatus.WARN
    assert [item["code"] for item in diagnostics] == [
        "reliability.retry.runner_owned",
        "reliability.timeout.unsupported",
    ]
    timeout_details = cast(dict[str, Any], diagnostics[1]["details"])
    assert timeout_details["timeout_domain"] == "reliability"


def test_unknown_executor_fails_resolve_and_skips_capability_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime_preflight_dependencies(monkeypatch)

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor", "resources"),
            runtime_options={"executor": "missing"},
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["executor.resolve"].status is PreflightCheckStatus.FAIL
    diagnostic = cast(dict[str, Any], by_id["executor.resolve"].details["diagnostic"])
    assert diagnostic["code"] == "executor.unknown"
    assert by_id["executor.capabilities"].status is PreflightCheckStatus.SKIP
    assert by_id["resources.capabilities"].status is PreflightCheckStatus.SKIP


def test_selected_subprocess_executor_runs_availability_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime_preflight_dependencies(monkeypatch)

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor",),
            runtime_options={"executor": "subprocess"},
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.PASS
    assert [check.check_id for check in result.checks] == [
        "executor.local",
        "executor.resolve",
        "executor.capabilities",
        "executor.subprocess.python",
        "executor.subprocess.worker",
    ]
    assert by_id["executor.resolve"].details["executor"] == "subprocess"
    assert by_id["executor.subprocess.python"].status is PreflightCheckStatus.PASS
    assert by_id["executor.subprocess.worker"].status is PreflightCheckStatus.PASS


def test_selected_subprocess_executor_fails_when_python_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    _patch_runtime_preflight_dependencies(monkeypatch)
    monkeypatch.setattr(
        preflight_module.sys,
        "executable",
        str(tmp_path / "missing-python"),
    )

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor",),
            runtime_options={"executor": "subprocess"},
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["executor.resolve"].status is PreflightCheckStatus.PASS
    assert by_id["executor.subprocess.python"].status is PreflightCheckStatus.FAIL
    assert by_id["executor.subprocess.python"].details["reason"] == (
        "not_found_or_not_executable"
    )


def test_selected_subprocess_executor_fails_when_worker_module_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    _patch_runtime_preflight_dependencies(monkeypatch)
    monkeypatch.setattr(
        preflight_module.importlib.util, "find_spec", lambda _name: None
    )

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor",),
            runtime_options={"executor": "subprocess"},
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["executor.resolve"].status is PreflightCheckStatus.PASS
    assert by_id["executor.subprocess.worker"].status is PreflightCheckStatus.FAIL
    assert by_id["executor.subprocess.worker"].details == {
        "module": "loom.cli.main",
        "command": "loom stage run",
        "reason": "module_not_found",
    }


def test_local_executor_does_not_run_subprocess_availability_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime_preflight_dependencies(monkeypatch)

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor",),
            runtime_options={"executor": "local"},
        )
    )

    assert [check.check_id for check in result.checks] == [
        "executor.local",
        "executor.resolve",
        "executor.capabilities",
    ]


def test_selected_docker_executor_runs_cheap_checks_and_redacts_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    _patch_runtime_preflight_dependencies(monkeypatch)
    monkeypatch.setattr(
        preflight_module.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name == "docker" else None,
    )
    monkeypatch.setenv("HOST_TOKEN", "host-secret")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("pipeline: {}\n", encoding="utf-8")
    mount_path = tmp_path / "mounted"
    mount_path.mkdir()
    run_uri = path_to_run_uri(tmp_path / "runs" / "docker-pass")

    result = run_preflight(
        PreflightRequest(
            config_path=config_path,
            groups=("executor", "resources", "filesystem"),
            run_uri=run_uri,
            runtime_options={
                "executor": "docker",
                "adapter_options": {
                    "container": {
                        "image": {"reference": "python:3.11-slim"},
                        "mounts": [
                            {
                                "source": str(mount_path),
                                "target": str(mount_path),
                                "mode": "rw",
                            }
                        ],
                        "environment": {
                            "variables": {"SECRET_TOKEN": "super-secret"},
                            "required_host_variables": ["HOST_TOKEN"],
                        },
                    },
                    "docker": {"command": "docker", "network": "none"},
                },
                "stage_options": {
                    "train": {
                        "resources": {
                            "entries": {
                                "cpu": {"kind": "cpu", "amount": 2},
                                "memory": {
                                    "kind": "memory",
                                    "amount": 1,
                                    "unit": "GiB",
                                },
                            }
                        }
                    }
                },
            },
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.PASS
    for check_id in (
        "executor.docker.command",
        "executor.docker.container_options",
        "executor.docker.image",
        "executor.docker.environment",
        "resources.docker.mapping",
        "resources.docker.gpu",
        "filesystem.docker.mount_sources",
        "filesystem.docker.mount_targets",
        "filesystem.docker.run_dir_writable",
        "filesystem.docker.artifact_root_visible",
    ):
        assert by_id[check_id].status is PreflightCheckStatus.PASS
    payload = json.dumps(result.to_dict(), sort_keys=True)
    assert "super-secret" not in payload
    assert "host-secret" not in payload
    assert "[redacted]" in payload
    assert not (tmp_path / "runs" / "docker-pass").exists()


def test_selected_docker_executor_fails_when_command_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    _patch_runtime_preflight_dependencies(monkeypatch)
    monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor",),
            runtime_options=_docker_runtime_options(),
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["executor.docker.command"].status is PreflightCheckStatus.FAIL
    commands = cast(
        list[dict[str, Any]],
        by_id["executor.docker.command"].details["commands"],
    )
    assert commands[0]["available"] is False


def test_selected_docker_executor_reports_missing_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    _patch_runtime_preflight_dependencies(monkeypatch)
    monkeypatch.setattr(
        preflight_module.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name == "docker" else None,
    )

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor",),
            runtime_options={
                "executor": "docker",
                "adapter_options": {"container": {"mounts": []}},
            },
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["executor.docker.container_options"].status is PreflightCheckStatus.FAIL
    assert by_id["executor.docker.image"].status is PreflightCheckStatus.FAIL
    diagnostics = cast(
        list[dict[str, Any]],
        by_id["executor.docker.image"].details["diagnostics"],
    )
    assert diagnostics[0]["code"] == "docker_image_invalid"


def test_selected_docker_filesystem_reports_mount_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    _patch_runtime_preflight_dependencies(monkeypatch)
    monkeypatch.setattr(
        preflight_module.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name == "docker" else None,
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text("pipeline: {}\n", encoding="utf-8")
    missing_mount = tmp_path / "missing"

    result = run_preflight(
        PreflightRequest(
            config_path=config_path,
            groups=("filesystem",),
            run_uri=path_to_run_uri(tmp_path / "runs" / "docker-fs"),
            runtime_options={
                "executor": "docker",
                "adapter_options": {
                    "container": {
                        "image": {"reference": "python:3.11-slim"},
                        "mounts": [
                            {
                                "source": str(missing_mount),
                                "target": str(missing_mount),
                                "mode": "ro",
                            },
                            {
                                "source": str(tmp_path),
                                "target": "/container-only",
                                "mode": "rw",
                            },
                        ],
                    }
                },
            },
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["filesystem.docker.mount_sources"].status is PreflightCheckStatus.FAIL
    assert by_id["filesystem.docker.mount_targets"].status is PreflightCheckStatus.FAIL
    missing = cast(
        list[dict[str, Any]],
        by_id["filesystem.docker.mount_sources"].details["missing"],
    )
    assert missing[0]["source"] == str(missing_mount)
    invalid = cast(
        list[dict[str, Any]],
        by_id["filesystem.docker.mount_targets"].details["invalid"],
    )
    assert invalid[0]["reason"] == "host_path and container_path must match in Stage 17"


def test_selected_docker_environment_reports_missing_required_host_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    _patch_runtime_preflight_dependencies(monkeypatch)
    monkeypatch.delenv("MISSING_HOST_TOKEN", raising=False)
    monkeypatch.setattr(
        preflight_module.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name == "docker" else None,
    )

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor",),
            runtime_options={
                "executor": "docker",
                "adapter_options": {
                    "container": {
                        "image": {"reference": "python:3.11-slim"},
                        "environment": {
                            "required_host_variables": ["MISSING_HOST_TOKEN"]
                        },
                    }
                },
            },
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["executor.docker.environment"].status is PreflightCheckStatus.FAIL
    missing = cast(
        list[dict[str, Any]],
        by_id["executor.docker.environment"].details[
            "missing_required_host_variables"
        ],
    )
    assert missing == [{"stage_id": "train", "name": "MISSING_HOST_TOKEN"}]


def test_selected_docker_resource_checks_fail_gpu_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime_preflight_dependencies(monkeypatch)

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("resources",),
            runtime_options={
                "executor": "docker",
                "adapter_options": {
                    "container": {"image": {"reference": "python:3.11-slim"}}
                },
                "stage_options": {
                    "train": {
                        "resources": {
                            "entries": {"gpu": {"kind": "gpu", "amount": 1}}
                        }
                    }
                },
            },
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["resources.capabilities"].status is PreflightCheckStatus.FAIL
    assert by_id["resources.docker.mapping"].status is PreflightCheckStatus.FAIL
    assert by_id["resources.docker.gpu"].status is PreflightCheckStatus.FAIL
    gpu_diagnostics = cast(
        list[dict[str, Any]],
        by_id["resources.docker.gpu"].details["diagnostics"],
    )
    assert gpu_diagnostics[0]["code"] == "docker_gpu_unsupported"


def test_slurm_dry_run_preflight_emits_stable_checks_and_warns_without_sbatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import loom.diagnostics.preflight as preflight_module
    from loom.pipeline.stores import path_to_run_uri

    _patch_runtime_preflight_dependencies(monkeypatch)
    monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("pipeline: {}\n", encoding="utf-8")
    run_uri = path_to_run_uri(tmp_path / "runs" / "dry")

    result = run_preflight(
        PreflightRequest(
            config_path=config_path,
            groups=("runtime", "run", "executor", "resources", "filesystem"),
            runtime_options={
                "run_uri": run_uri,
                "executor": "slurm-afterok",
                "dry_run": True,
                "adapter_options": {
                    "slurm": {
                        "schema_version": 1,
                        "launcher_argv": ["loom", "--profile", "batch"],
                    }
                },
                "stage_options": {
                    "train": {
                        "resources": {
                            "entries": {
                                "cpu": {"kind": "cpu", "amount": 2},
                                "memory": {
                                    "kind": "memory",
                                    "amount": 4,
                                    "unit": "GiB",
                                },
                                "gpu": {"kind": "gpu", "amount": 0},
                            }
                        }
                    }
                },
            },
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.WARN
    for check_id in (
        "runtime.slurm.options",
        "run_uri.slurm.local",
        "executor.slurm.mode",
        "executor.slurm.launcher",
        "executor.slurm.sbatch",
        "resources.slurm.mapping",
        "filesystem.slurm.generated_paths",
    ):
        assert check_id in by_id
    assert by_id["executor.slurm.sbatch"].status is PreflightCheckStatus.WARN
    assert by_id["executor.slurm.sbatch"].details["available"] is False
    assert by_id["executor.slurm.mode"].status is PreflightCheckStatus.PASS
    assert by_id["resources.slurm.mapping"].status is PreflightCheckStatus.PASS


def test_slurm_afterok_live_preflight_requires_sbatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    _patch_runtime_preflight_dependencies(monkeypatch)
    monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor",),
            runtime_options={"executor": "slurm-afterok"},
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["executor.resolve"].status is PreflightCheckStatus.PASS
    assert by_id["executor.slurm.mode"].status is PreflightCheckStatus.PASS
    assert by_id["executor.slurm.mode"].details["live_submission"] is True
    assert by_id["executor.slurm.sbatch"].status is PreflightCheckStatus.FAIL


def test_slurm_single_job_live_preflight_requires_sbatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    _patch_runtime_preflight_dependencies(monkeypatch)
    monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor",),
            runtime_options={"executor": "slurm-single-job"},
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["executor.slurm.mode"].status is PreflightCheckStatus.PASS
    assert by_id["executor.slurm.mode"].details["live_submission"] is True
    assert by_id["executor.slurm.sbatch"].status is PreflightCheckStatus.FAIL
    assert by_id["executor.slurm.sbatch"].details["required"] is True


def test_slurm_live_preflight_warns_for_optional_status_and_cancel_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    _patch_runtime_preflight_dependencies(monkeypatch)
    monkeypatch.setattr(
        preflight_module.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name == "sbatch" else None,
    )

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor",),
            runtime_options={"executor": "slurm-afterok"},
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.WARN
    assert by_id["executor.slurm.sbatch"].status is PreflightCheckStatus.PASS
    for check_id in (
        "executor.slurm.squeue",
        "executor.slurm.sacct",
        "executor.slurm.scancel",
    ):
        assert by_id[check_id].status is PreflightCheckStatus.WARN
        assert by_id[check_id].details["required"] is False


def test_slurm_run_preflight_fails_existing_active_submission(
    tmp_path,
) -> None:
    from loom.pipeline.execution import create_authority_backed_serial_run_store
    from loom.pipeline.stores import path_to_run_uri
    from loom.pipeline.stores.service_authority import LocalAuthorityService
    from loom.pipeline.submitted import (
        SubmittedOperationRecord,
        SubmittedOperationState,
    )

    run_uri = path_to_run_uri(tmp_path / "runs" / "active")
    with LocalAuthorityService.start() as service:
        authority_config = service.config()
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_config=authority_config,
        )
        store.create_run(run_uri)
        store.write_submitted_operation(
            run_uri,
            SubmittedOperationRecord(
                run_uri=run_uri,
                submission_id="planning-1",
                backend="slurm",
                mode="slurm-afterok",
                created_at="2026-05-08T00:00:00Z",
                updated_at="2026-05-08T00:00:01Z",
                state=SubmittedOperationState.SUBMITTED,
                manifest_relative_path="slurm/submissions/planning-1/manifest.json",
                summary_counts={"submitted": 1, "active": 1},
            ),
        )

        result = run_preflight(
            PreflightRequest(
                config_path="config.yaml",
                groups=("run",),
                run_uri=run_uri,
                runtime_options={
                    "executor": "slurm-afterok",
                    "resume": {"enabled": True},
                },
                authority_config=authority_config,
            )
        )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["run_uri.resolve"].status is PreflightCheckStatus.PASS
    assert (
        by_id["run_uri.slurm.active_submission"].status
        is PreflightCheckStatus.FAIL
    )
    source = cast(
        dict[str, Any],
        by_id["run_uri.slurm.active_submission"].details["state_source"],
    )
    assert source["label"] == "authoritative_service_truth"
    assert by_id["run_uri.slurm.active_submission"].details["submission_id"] == (
        "planning-1"
    )


def test_slurm_filesystem_preflight_probes_generated_path_writability(
    tmp_path,
) -> None:
    from loom.pipeline.stores import path_to_run_uri

    config_path = tmp_path / "config.yaml"
    config_path.write_text("pipeline: {}\n", encoding="utf-8")
    run_uri = path_to_run_uri(tmp_path / "runs" / "writable")

    result = run_preflight(
        PreflightRequest(
            config_path=config_path,
            groups=("filesystem",),
            run_uri=run_uri,
            runtime_options={
                "executor": "slurm-afterok",
                "dry_run": True,
            },
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.PASS
    assert by_id["filesystem.slurm.generated_paths"].status is PreflightCheckStatus.PASS
    assert (
        by_id["filesystem.slurm.generated_writable"].status
        is PreflightCheckStatus.PASS
    )
    assert not (tmp_path / "runs" / "writable").exists()


@dataclass(frozen=True, slots=True)
class _FakeComposedConfig:
    resolved: dict[str, object]
    source_artifacts: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class _FakeSpec:
    stage_names: tuple[str, ...] = ("train",)


@dataclass(frozen=True, slots=True)
class _FakePipelineValidation:
    spec: _FakeSpec = _FakeSpec()
    graph: object = object()
    stage_count: int = 1
    pipeline_name: str = "demo"


def _patch_runtime_preflight_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    import loom.pipeline

    config_package = ModuleType("loom.config")
    config_api = ModuleType("loom.config.api")
    setattr(
        config_api,
        "compose_config",
        lambda *_args, **_kwargs: _FakeComposedConfig(resolved={"pipeline": {}}),
    )
    setattr(config_package, "api", config_api)
    monkeypatch.setitem(sys.modules, "loom.config", config_package)
    monkeypatch.setitem(sys.modules, "loom.config.api", config_api)
    monkeypatch.setattr(
        loom.pipeline,
        "validate_pipeline_config",
        lambda _config: _FakePipelineValidation(),
    )


def _docker_runtime_options() -> dict[str, object]:
    return {
        "executor": "docker",
        "adapter_options": {
            "container": {"image": {"reference": "python:3.11-slim"}}
        },
    }
