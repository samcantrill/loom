"""Unit tests for the local preflight runner."""

from __future__ import annotations

from dataclasses import dataclass
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
    assert [check.status for check in result.checks] == [
        PreflightCheckStatus.SKIP,
        PreflightCheckStatus.SKIP,
    ]
    assert [check.details["reason"] for check in result.checks] == [
        "missing_run_uri",
        "missing_run_uri",
    ]


def test_run_uri_group_uses_explicit_runtime_run_uri_without_config(
    tmp_path,
) -> None:
    from loom.pipeline.stores import path_to_run_uri

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
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
    from loom.pipeline.submitted import (
        SubmittedOperationRecord,
        SubmittedOperationState,
    )

    store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=SQLitePerRunAuthorityStore(),
    )
    run_uri = path_to_run_uri(tmp_path / "runs" / "active")
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
            runtime_options={"executor": "slurm-afterok", "resume": {"enabled": True}},
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["run_uri.resolve"].status is PreflightCheckStatus.PASS
    assert (
        by_id["run_uri.slurm.active_submission"].status
        is PreflightCheckStatus.FAIL
    )
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
