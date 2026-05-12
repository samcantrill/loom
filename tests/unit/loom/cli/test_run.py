"""Unit tests for ``loom run`` command orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
from pathlib import Path

import pytest

from loom.cli.errors import CliError
from loom.cli.main import main
from loom.cli.options import ConfigCliOptions
from loom.cli.results import PlanCliResult, RunCliResult
from loom.cli.results import SlurmDryRunCliResult, SlurmLiveRunCliResult
import loom.cli.plan as plan_command
import loom.cli.run as run_command
from loom.diagnostics import (
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightRequest,
    PreflightResult,
    PreflightSeverity,
)
from loom.pipeline.planning import PlanAction, PlanReason, PlanReasonCode
from loom.pipeline.runtime import RunOptions
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AuthorityFactoryError,
    AuthorityResolutionFailureKind,
    AuthorityResolutionMode,
    LocalRunStore,
)


pytestmark = pytest.mark.unit


def test_run_default_store_is_authority_backed_serial_store() -> None:
    with pytest.raises(AuthorityFactoryError) as exc_info:
        run_command._create_default_run_store()

    error = exc_info.value
    assert error.code == "authority_factory.resolution_failed"
    assert error.resolution is not None
    assert (
        error.resolution.failure_kind
        is AuthorityResolutionFailureKind.MISSING_AUTHORITY
    )


def test_run_default_store_can_be_explicit_offline_evidence_store() -> None:
    store = run_command._create_default_run_store(
        authority_mode=AuthorityResolutionMode.OFFLINE_FIRST
    )

    assert getattr(store, "offline_evidence_enabled") is True
    assert store.state_source["authoritative"] is False


@dataclass(frozen=True, slots=True)
class FakeComposedConfig:
    resolved: dict[str, object]


@dataclass(frozen=True, slots=True)
class FakeSpec:
    stage_names: tuple[str, ...] = ("build",)


@dataclass(frozen=True, slots=True)
class FakePipelineResult:
    spec: FakeSpec = FakeSpec()


@dataclass(frozen=True, slots=True)
class FakePlan:
    summary: dict[str, int]
    stage_order: tuple[str, ...] = ("build",)


@dataclass(frozen=True, slots=True)
class FakeStageResult:
    action: PlanAction = PlanAction.RUN
    status: StageStatus | None = StageStatus.SUCCEEDED
    attempt: int | None = 1
    outputs: dict[str, object] | None = None
    failure: object | None = None
    reasons: tuple[PlanReason, ...] = (
        PlanReason(
            PlanReasonCode.RESUME_DISABLED, "resume is disabled", stage_name="build"
        ),
    )

    def __post_init__(self) -> None:
        if self.outputs is None:
            object.__setattr__(self, "outputs", {"data": object()})


@dataclass(frozen=True, slots=True)
class FakeFailure:
    run_uri: str = "file:///abs/runs/generated"
    stage_name: str = "build"
    attempt: int = 1
    executor: str = "local"
    failure_type: str = "stage_exception"
    message: str = "boom"
    exception_type: str | None = "builtins.RuntimeError"
    exit_code: int | None = None
    signal: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    traceback_path: str | None = None


@dataclass(frozen=True, slots=True)
class FakeRunResult:
    run_uri: str = "file:///abs/runs/generated"
    status: RunStatus = RunStatus.SUCCEEDED
    plan: FakePlan = FakePlan(summary={"RUN": 1, "REUSE": 0})
    stage_results: dict[str, FakeStageResult] | None = None
    failure: FakeFailure | None = None
    artifact_index: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.stage_results is None:
            object.__setattr__(self, "stage_results", {"build": FakeStageResult()})
        if self.artifact_index is None:
            object.__setattr__(self, "artifact_index", {"build.data": object()})


@dataclass(frozen=True, slots=True)
class FakeRunRequest:
    run_uri: str | None
    open_existing: bool
    options: RunOptions


def _preflight_result(
    status: PreflightCheckStatus = PreflightCheckStatus.PASS,
) -> PreflightResult:
    severity = (
        PreflightSeverity.ERROR
        if status is PreflightCheckStatus.FAIL
        else PreflightSeverity.INFO
    )
    return PreflightResult(
        checks=(
            PreflightCheckResult(
                check_id="config.load",
                group=PreflightGroup.CONFIG,
                status=status,
                severity=severity,
                message="config composed successfully",
            ),
        ),
        groups=(PreflightGroup.CONFIG,),
    )


class FakeRunStore:
    def __init__(self, *, exists: bool = False) -> None:
        self.exists = exists
        self.opened: list[str] = []
        self.allocated = 0

    def resolve_run_uri(self, run_uri: str) -> str:
        assert run_uri == "file://./runs/demo"
        return "file:///abs/runs/demo"

    def open_run(self, run_uri: str) -> None:
        self.opened.append(run_uri)

    def run_uri_exists(self, run_uri: str) -> bool:
        assert run_uri == "file:///abs/runs/demo"
        return self.exists

    def allocate_run_uri(self) -> str:
        self.allocated += 1
        return "file:///abs/runs/generated"


def _patch_common(
    monkeypatch: pytest.MonkeyPatch, *, store: FakeRunStore | None = None
) -> dict[str, object]:
    calls: dict[str, object] = {}
    fake_store = store or FakeRunStore()

    def compose(
        config_path: object, *, overlays: tuple[Path, ...], overrides: tuple[str, ...]
    ) -> FakeComposedConfig:
        calls["config_path"] = config_path
        calls["overlays"] = overlays
        calls["overrides"] = overrides
        return FakeComposedConfig(resolved={"pipeline": {}})

    def run_pipeline(
        request: object,
        run_store: object,
        *,
        executor: object,
    ) -> FakeRunResult:
        calls["request_run_uri"] = getattr(request, "run_uri")
        calls["open_existing"] = getattr(request, "open_existing")
        calls["request_options"] = getattr(request, "options")
        calls["run_store"] = run_store
        calls["executor"] = executor
        return FakeRunResult()

    def build_run_request(
        _config: object,
        *,
        open_existing: bool,
        options: RunOptions,
    ) -> FakeRunRequest:
        return FakeRunRequest(
            run_uri=options.run_uri,
            open_existing=open_existing,
            options=options,
        )

    def run_preflight(
        *,
        config_options: object,
        runtime_options: object,
        open_existing: bool,
        authority_config: object | None = None,
        authority_mode: object | None = None,
    ) -> None:
        calls["preflight_authority_config"] = authority_config
        calls["preflight_authority_mode"] = authority_mode
        calls["preflight_config_path"] = getattr(config_options, "config_path")
        calls["preflight_resume"] = open_existing
        calls["preflight_run_uri"] = getattr(runtime_options, "run_uri")

    monkeypatch.setattr(run_command, "_compose_config", compose)
    monkeypatch.setattr(
        run_command, "_validate_pipeline_config", lambda _config: FakePipelineResult()
    )
    monkeypatch.setattr(
        run_command,
        "_create_default_run_store",
        lambda *, authority_config=None, authority_mode=None: fake_store,
    )
    monkeypatch.setattr(run_command, "_build_run_request", build_run_request)
    monkeypatch.setattr(run_command, "_run_preflight_for_run", run_preflight)
    monkeypatch.setattr(run_command, "_run_pipeline", run_pipeline)
    return calls


def test_run_default_uri_is_allocated_once_before_preflight_and_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_common(monkeypatch)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "run",
                "base.yaml",
                "--overlay",
                "team.yaml",
                "--set",
                "a=1",
                "--only-stage",
                "build",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert "OK run file:///abs/runs/generated: SUCCEEDED" in stdout.getvalue()
    assert stderr.getvalue() == ""
    assert calls["config_path"] == Path("base.yaml")
    assert calls["overlays"] == (Path("team.yaml"),)
    assert calls["overrides"] == ("a=1",)
    assert calls["preflight_config_path"] == Path("base.yaml")
    assert calls["preflight_run_uri"] == "file:///abs/runs/generated"
    assert calls["request_run_uri"] == "file:///abs/runs/generated"
    options = calls["request_options"]
    assert isinstance(options, RunOptions)
    assert options.to_plan_selectors().only_stages == ("build",)


def test_run_explicit_existing_uri_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch, store=FakeRunStore(exists=True))
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", "base.yaml", "--run-uri", "file://./runs/demo", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 4
    )

    payload = json.loads(stdout.getvalue())
    assert stderr.getvalue() == ""
    assert payload["error"]["type"] == "RunAlreadyExistsError"


def test_run_resume_requires_run_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["run", "base.yaml", "--resume"], stdout=stdout, stderr=stderr) == 4
    assert "`loom run --resume` requires --run-uri" in stderr.getvalue()


def test_run_resume_opens_existing_run(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeRunStore()
    calls = _patch_common(monkeypatch, store=store)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", "base.yaml", "--run-uri", "file://./runs/demo", "--resume"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert store.opened == ["file:///abs/runs/demo"]
    assert calls["preflight_resume"] is True
    assert calls["preflight_run_uri"] == "file:///abs/runs/demo"
    assert calls["request_run_uri"] == "file:///abs/runs/demo"
    assert calls["open_existing"] is True


def test_run_preflight_helper_skips_fresh_run_group_for_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, PreflightRequest] = {}

    def run_preflight(request: PreflightRequest) -> PreflightResult:
        calls["request"] = request
        return _preflight_result()

    monkeypatch.setattr(run_command, "_run_diagnostics_preflight", run_preflight)

    run_command._run_preflight_for_run(
        config_options=ConfigCliOptions(config_path=Path("base.yaml")),
        runtime_options=RunOptions(run_uri="file:///abs/runs/demo"),
        open_existing=True,
    )

    assert calls["request"].groups == (
        "config",
        "pipeline",
        "selectors",
        "runtime",
        "executor",
        "resources",
    )


def test_run_preflight_failure_stops_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_preflight(_request: PreflightRequest) -> PreflightResult:
        return _preflight_result(PreflightCheckStatus.FAIL)

    monkeypatch.setattr(run_command, "_run_diagnostics_preflight", fail_preflight)

    with pytest.raises(CliError) as exc_info:
        run_command._run_preflight_for_run(
            config_options=ConfigCliOptions(config_path=Path("base.yaml")),
            runtime_options=RunOptions(run_uri="file:///abs/runs/demo"),
            open_existing=False,
        )

    assert exc_info.value.code == "cli.run.preflight_failed"
    assert exc_info.value.exit_code == 4
    preflight_details = exc_info.value.details["preflight"]
    assert isinstance(preflight_details, dict)
    assert preflight_details["status"] == "FAIL"


def test_run_unsupported_executor_returns_executor_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common(monkeypatch)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", "base.yaml", "--executor", "slurm", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 7
    )

    payload = json.loads(stdout.getvalue())
    assert stderr.getvalue() == ""
    assert payload["error"]["code"] == "cli.run.unsupported_executor"


def test_run_non_dry_run_slurm_afterok_uses_live_result_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build_slurm_result(*_args: object, **_kwargs: object) -> SlurmLiveRunCliResult:
        return SlurmLiveRunCliResult(
            run_uri="file:///abs/runs/live",
            mode="slurm-afterok",
            submission_id="planning-1",
            status="SUBMITTED",
            manifest_path="/abs/runs/live/slurm/submissions/planning-1/manifest.json",
            manifest_relative_path="slurm/submissions/planning-1/manifest.json",
            plan_path="/abs/runs/live/slurm/submissions/planning-1/plan.json",
            plan_relative_path="slurm/submissions/planning-1/plan.json",
            submitted_jobs=(
                {
                    "logical_key": "stage:build",
                    "scheduler_job_id": "1234",
                    "scheduler_cluster": None,
                },
            ),
            job_count=1,
            submitted_job_count=1,
        )

    monkeypatch.setattr(
        run_command, "build_slurm_live_submission_result", build_slurm_result
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", "base.yaml", "--executor", "slurm-afterok", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert stderr.getvalue() == ""
    assert payload["schema_version"] == "loom.cli.slurm_live_run.v1"
    assert payload["result"]["mode"] == "slurm-afterok"
    assert payload["result"]["submitted_jobs"][0]["scheduler_job_id"] == "1234"


def test_run_build_executor_supports_subprocess(tmp_path: Path) -> None:
    executor = run_command._build_executor(
        "subprocess",
        LocalRunStore(tmp_path / "runs"),
    )

    assert getattr(executor, "name") == "subprocess"
    assert getattr(executor, "requires_prepared_worker_request") is True


def test_run_dry_run_uses_plan_result_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    def build_plan_result(*_args: object, **_kwargs: object) -> PlanCliResult:
        return PlanCliResult(
            config_path=Path("base.yaml"),
            stage_actions=(
                {
                    "stage": "build",
                    "action": "RUN",
                    "reason_codes": ("RESUME_DISABLED",),
                },
            ),
        )

    monkeypatch.setattr(
        run_command, "_dry_run_selects_slurm_executor", lambda **_kwargs: False
    )
    monkeypatch.setattr(plan_command, "build_plan_result", build_plan_result)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", "base.yaml", "--dry-run", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.plan.v2"
    assert payload["result"]["stage_actions"][0]["stage"] == "build"


def test_run_slurm_dry_run_uses_slurm_result_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build_slurm_result(
        *_args: object, **_kwargs: object
    ) -> tuple[SlurmDryRunCliResult, tuple[object, ...]]:
        return (
            SlurmDryRunCliResult(
                run_uri="file:///abs/runs/dry",
                mode="slurm-single-job",
                planning_id="planning-1",
                manifest_path="/abs/runs/dry/slurm/submissions/planning-1/manifest.json",
                manifest_relative_path="slurm/submissions/planning-1/manifest.json",
                plan_path="/abs/runs/dry/slurm/submissions/planning-1/plan.json",
                plan_relative_path="slurm/submissions/planning-1/plan.json",
                script_directory="/abs/runs/dry/slurm/submissions/planning-1/scripts",
                script_count=1,
                job_count=1,
                dependency_count=0,
            ),
            (),
        )

    def fail_plan(*_args: object, **_kwargs: object) -> PlanCliResult:
        raise AssertionError("SLURM dry-run must not use generic plan output")

    monkeypatch.setattr(run_command, "build_slurm_dry_run_result", build_slurm_result)
    monkeypatch.setattr(plan_command, "build_plan_result", fail_plan)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "run",
                "base.yaml",
                "--executor",
                "slurm-single-job",
                "--dry-run",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert stderr.getvalue() == ""
    assert payload["schema_version"] == "loom.cli.slurm_dry_run.v1"
    assert payload["result"]["mode"] == "slurm-single-job"
    assert payload["result"]["script_count"] == 1


def test_run_slurm_live_single_job_uses_live_result_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build_slurm_result(*_args: object, **_kwargs: object) -> SlurmLiveRunCliResult:
        return SlurmLiveRunCliResult(
            run_uri="file:///abs/runs/live",
            mode="slurm-single-job",
            submission_id="planning-1",
            status="SUBMITTED",
            manifest_path="/abs/runs/live/slurm/submissions/planning-1/manifest.json",
            manifest_relative_path="slurm/submissions/planning-1/manifest.json",
            plan_path="/abs/runs/live/slurm/submissions/planning-1/plan.json",
            plan_relative_path="slurm/submissions/planning-1/plan.json",
            submitted_jobs=(
                {
                    "logical_key": "pipeline",
                    "scheduler_job_id": "1234",
                    "scheduler_cluster": None,
                },
            ),
            job_count=1,
            submitted_job_count=1,
        )

    def fail_generic_run(*_args: object, **_kwargs: object) -> RunCliResult:
        raise AssertionError("SLURM live submission must not use generic run output")

    monkeypatch.setattr(
        run_command, "build_slurm_live_submission_result", build_slurm_result
    )
    monkeypatch.setattr(run_command, "build_run_result", fail_generic_run)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "run",
                "base.yaml",
                "--executor",
                "slurm-single-job",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert stderr.getvalue() == ""
    assert payload["schema_version"] == "loom.cli.slurm_live_run.v1"
    assert payload["result"]["mode"] == "slurm-single-job"
    assert payload["result"]["status"] == "SUBMITTED"
    assert payload["result"]["submitted_jobs"][0]["scheduler_job_id"] == "1234"


def test_run_slurm_live_afterok_partial_returns_run_failed_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build_slurm_result(*_args: object, **_kwargs: object) -> SlurmLiveRunCliResult:
        return SlurmLiveRunCliResult(
            run_uri="file:///abs/runs/live",
            mode="slurm-afterok",
            submission_id="planning-1",
            status="PARTIAL",
            manifest_path="/abs/runs/live/slurm/submissions/planning-1/manifest.json",
            manifest_relative_path="slurm/submissions/planning-1/manifest.json",
            plan_path="/abs/runs/live/slurm/submissions/planning-1/plan.json",
            plan_relative_path="slurm/submissions/planning-1/plan.json",
            submitted_jobs=(
                {
                    "logical_key": "stage:build",
                    "scheduler_job_id": "1234",
                    "scheduler_cluster": None,
                },
            ),
            failed_submissions=(
                {
                    "logical_key": "stage:train",
                    "reason": "partition unavailable",
                },
            ),
            job_count=2,
            submitted_job_count=1,
            failed_submission_count=1,
        )

    monkeypatch.setattr(
        run_command, "build_slurm_live_submission_result", build_slurm_result
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", "base.yaml", "--executor", "slurm-afterok", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 5
    )

    payload = json.loads(stdout.getvalue())
    assert stderr.getvalue() == ""
    assert payload["ok"] is False
    assert payload["result"]["status"] == "PARTIAL"
    assert payload["result"]["failed_submission_count"] == 1


def test_run_failed_result_returns_run_failed_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common(monkeypatch)

    def failed_run(
        _request: object,
        _run_store: object,
        *,
        executor: object,
    ) -> FakeRunResult:
        assert getattr(executor, "name") == "local"
        failure = FakeFailure()
        return FakeRunResult(
            status=RunStatus.FAILED,
            stage_results={
                "build": FakeStageResult(
                    status=StageStatus.FAILED,
                    outputs={},
                    failure=failure,
                )
            },
            failure=failure,
            artifact_index={},
        )

    monkeypatch.setattr(run_command, "_run_pipeline", failed_run)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(["run", "base.yaml", "--format", "json"], stdout=stdout, stderr=stderr)
        == 5
    )

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["result"]["status"] == "FAILED"
    assert payload["result"]["failure_summary"]["message"] == "boom"


def test_failure_summary_includes_subprocess_failure_facts() -> None:
    summary = run_command._failure_summary(
        FakeFailure(
            attempt=2,
            executor="subprocess",
            exit_code=None,
            signal=9,
            stdout_path="/tmp/run/stages/build/logs/stdout.log",
            stderr_path="/tmp/run/stages/build/logs/stderr.log",
            traceback_path="/tmp/run/stages/build/logs/traceback.txt",
        )
    )

    assert summary == {
        "stage": "build",
        "attempt": 2,
        "executor": "subprocess",
        "failure_type": "stage_exception",
        "message": "boom",
        "exception_type": "builtins.RuntimeError",
        "exit_code": None,
        "signal": 9,
        "stdout_path": "/tmp/run/stages/build/logs/stdout.log",
        "stderr_path": "/tmp/run/stages/build/logs/stderr.log",
        "traceback_path": "/tmp/run/stages/build/logs/traceback.txt",
        "failure_path": "/abs/runs/generated/stages/build/failure.json",
    }
