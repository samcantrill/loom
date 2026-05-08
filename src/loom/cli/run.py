"""Implementation for ``loom run``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import (
    format_json_envelope,
    format_run_text,
    format_slurm_dry_run_text,
)
from loom.cli.options import (
    ConfigCliOptions,
    OutputFormat,
    PlanCliOptions,
    RunCliOptions,
    SelectorCliOptions,
    output_format_from_namespace,
)
from loom.cli.results import CliWarning, RunCliResult, SlurmDryRunCliResult

if TYPE_CHECKING:
    from loom.diagnostics import PreflightRequest, PreflightResult
    from loom.config.api import ComposedConfig
    from loom.pipeline.execution import RunRequest, RunResult
    from loom.pipeline.executors.slurm import SlurmDryRunPlanningResult, SlurmOptions
    from loom.pipeline.executors import Executor
    from loom.pipeline.planning import ExecutionPlan, PlanSelectors
    from loom.pipeline.runtime import RunOptions
    from loom.pipeline.specs import PipelineSpec
    from loom.pipeline.stores import LocalRunStore
    from loom.pipeline.validation import PipelineValidationResult
    from loom.serialization import PlainData


RUN_RESULT_SCHEMA_VERSION = "loom.cli.run.v2"
SLURM_DRY_RUN_RESULT_SCHEMA_VERSION = "loom.cli.slurm_dry_run.v1"
_SLURM_EXECUTORS = frozenset({"slurm-single-job", "slurm-afterok"})


class UnsupportedExecutorError(CliError):
    """Raised when ``loom run`` receives an unsupported executor name."""

    def __init__(self, executor: str) -> None:
        super().__init__(
            f"unsupported executor {executor!r}; supported executors: local, subprocess.",
            code="cli.run.unsupported_executor",
            context={"executor": executor, "supported": ["local", "subprocess"]},
            exit_code=ExitCode.EXECUTOR,
        )


class SlurmLiveSubmissionDeferredError(CliError):
    """Raised when v6 CLI receives a live SLURM executor selection."""

    def __init__(self, executor: str) -> None:
        super().__init__(
            f"SLURM executor {executor!r} only supports --dry-run in this build; live submission is deferred to v7.",
            code="cli.run.slurm_live_submission_deferred",
            hint="Re-run with --dry-run to generate SLURM scripts and manifests without submitting jobs.",
            context={"executor": executor, "dry_run_supported": True, "deferred_to": "v7"},
            exit_code=ExitCode.EXECUTOR,
        )


def register_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the run subcommand."""

    parser = subparsers.add_parser("run", help="run a pipeline")
    parser.add_argument("config", metavar="CONFIG", help="pipeline config path")
    parser.add_argument(
        "--overlay",
        action="append",
        default=None,
        metavar="PATH",
        help="additional config overlay path",
    )
    parser.add_argument(
        "--set",
        dest="override",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="config override expression",
    )
    parser.add_argument("--run-uri", metavar="URI", help="explicit run URI")
    parser.add_argument("--profile", metavar="NAME", help="runtime profile to select")
    parser.add_argument("--executor", default=None, metavar="NAME", help="executor name")
    parser.add_argument("--resume", action="store_true", help="resume an existing run")
    parser.add_argument("--dry-run", action="store_true", help="plan without executing")
    parser.add_argument(
        "--tag",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="runtime tag; may be repeated",
    )
    parser.add_argument(
        "--note",
        action="append",
        default=None,
        metavar="TEXT",
        help="runtime note; may be repeated",
    )
    parser.add_argument("--from-stage", metavar="STAGE", help="start at a stage")
    parser.add_argument(
        "--only-stage",
        action="append",
        default=None,
        metavar="STAGE",
        help="include only a selected stage",
    )
    parser.add_argument(
        "--force-stage",
        action="append",
        default=None,
        metavar="STAGE",
        help="force a selected stage",
    )
    parser.add_argument(
        "--skip-stage",
        action="append",
        default=None,
        metavar="STAGE",
        help="skip a selected stage",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=[format.value for format in OutputFormat],
        default=OutputFormat.TEXT.value,
        help="output format",
    )
    parser.add_argument(
        "--traceback",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show traceback details for errors",
    )
    parser.set_defaults(handler=handle)


def handle(namespace: argparse.Namespace) -> int:
    """Handle ``loom run``."""

    config_options = ConfigCliOptions.from_namespace(namespace)
    run_options = RunCliOptions.from_namespace(namespace)
    selector_options = SelectorCliOptions.from_namespace(namespace)
    output_format = output_format_from_namespace(namespace)

    if run_options.dry_run:
        return _handle_dry_run(
            config_options=config_options,
            run_options=run_options,
            selector_options=selector_options,
            output_format=output_format,
        )

    result = build_run_result(
        config_options=config_options,
        run_options=run_options,
        selector_options=selector_options,
    )
    ok = result.status == "SUCCEEDED"
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=RUN_RESULT_SCHEMA_VERSION,
                ok=ok,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_run_text(result) + "\n")
    return int(ExitCode.SUCCESS if ok else ExitCode.RUN_FAILED)


def build_run_result(
    *,
    config_options: ConfigCliOptions,
    run_options: RunCliOptions,
    selector_options: SelectorCliOptions,
) -> RunCliResult:
    """Execute a pipeline and build the CLI-specific run result."""

    store = _create_default_run_store()
    composed = _compose_config(
        config_options.config_path,
        overlays=config_options.overlays,
        overrides=config_options.overrides,
    )
    pipeline_result = _validate_pipeline_config(composed.resolved)
    runtime_options = _merge_runtime_options(
        composed.resolved,
        run_options=run_options,
        selector_options=selector_options,
        known_stage_ids=pipeline_result.spec.stage_names,
    )
    if _is_slurm_executor(runtime_options.executor):
        raise SlurmLiveSubmissionDeferredError(cast(str, runtime_options.executor))
    run_uri = _resolve_run_uri_for_run(
        store,
        runtime_options.run_uri,
        open_existing=run_options.resume,
    )
    runtime_options = _with_resolved_run_uri(runtime_options, run_uri)
    executor = _build_executor(runtime_options.executor or "local", store)
    _run_preflight_for_run(
        config_options=config_options,
        runtime_options=runtime_options,
        open_existing=run_options.resume,
    )
    request = _build_run_request(
        composed,
        open_existing=run_options.resume,
        options=runtime_options,
    )
    result = _run_pipeline(request, store, executor=executor)
    return _run_result_from_execution_result(result)


def _handle_dry_run(
    *,
    config_options: ConfigCliOptions,
    run_options: RunCliOptions,
    selector_options: SelectorCliOptions,
    output_format: OutputFormat,
) -> int:
    if _dry_run_selects_slurm_executor(
        config_options=config_options,
        run_options=run_options,
        selector_options=selector_options,
    ):
        result, warnings = build_slurm_dry_run_result(
            config_options=config_options,
            run_options=run_options,
            selector_options=selector_options,
        )
        if output_format is OutputFormat.JSON:
            sys.stdout.write(
                format_json_envelope(
                    schema_version=SLURM_DRY_RUN_RESULT_SCHEMA_VERSION,
                    ok=True,
                    warnings=warnings,
                    payload_name="result",
                    payload=result.to_dict(),
                )
            )
        else:
            sys.stdout.write(format_slurm_dry_run_text(result) + "\n")
        return int(ExitCode.SUCCESS)

    from loom.cli.plan import PLAN_RESULT_SCHEMA_VERSION, build_plan_result

    plan_result = build_plan_result(
        config_options=config_options,
        plan_options=PlanCliOptions(
            run_uri=run_options.run_uri,
            resume=run_options.resume,
            profile=run_options.profile,
            executor=run_options.executor if run_options.executor_explicit else None,
            explain_stage=None,
            tags=run_options.tags,
            notes=run_options.notes,
        ),
        selector_options=selector_options,
    )
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=PLAN_RESULT_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=plan_result.to_dict(),
            )
        )
    else:
        from loom.cli.formatting import format_plan_text

        sys.stdout.write(format_plan_text(plan_result) + "\n")
    return int(ExitCode.SUCCESS)


def _dry_run_selects_slurm_executor(
    *,
    config_options: ConfigCliOptions,
    run_options: RunCliOptions,
    selector_options: SelectorCliOptions,
) -> bool:
    if run_options.executor_explicit:
        return _is_slurm_executor(run_options.executor)

    composed = _compose_config(
        config_options.config_path,
        overlays=config_options.overlays,
        overrides=config_options.overrides,
    )
    pipeline_result = _validate_pipeline_config(composed.resolved)
    runtime_options = _merge_runtime_options(
        composed.resolved,
        run_options=run_options,
        selector_options=selector_options,
        known_stage_ids=pipeline_result.spec.stage_names,
    )
    return _is_slurm_executor(runtime_options.executor)


def build_slurm_dry_run_result(
    *,
    config_options: ConfigCliOptions,
    run_options: RunCliOptions,
    selector_options: SelectorCliOptions,
) -> tuple[SlurmDryRunCliResult, tuple[CliWarning, ...]]:
    """Prepare persisted state and invoke the public SLURM dry-run planners."""

    store = _create_default_run_store()
    composed = _compose_config(
        config_options.config_path,
        overlays=config_options.overlays,
        overrides=config_options.overrides,
    )
    pipeline_result = _validate_pipeline_config(composed.resolved)
    runtime_options = _merge_runtime_options(
        composed.resolved,
        run_options=run_options,
        selector_options=selector_options,
        known_stage_ids=pipeline_result.spec.stage_names,
    )
    executor = runtime_options.executor or "local"
    if not _is_slurm_executor(executor):
        raise UnsupportedExecutorError(executor)

    run_uri = _resolve_run_uri_for_run(
        store,
        runtime_options.run_uri,
        open_existing=run_options.resume,
    )
    if run_uri is None:
        raise CliError(
            "SLURM dry-run requires a resolved local run URI.",
            code="cli.run.slurm_missing_run_uri",
            exit_code=ExitCode.PIPELINE,
        )
    runtime_options = _with_resolved_run_uri(runtime_options, run_uri)
    preflight = _run_preflight_for_slurm_dry_run(
        config_options=config_options,
        runtime_options=runtime_options,
        open_existing=run_options.resume,
    )
    warnings = _preflight_cli_warnings(preflight)
    if not run_options.resume:
        store.create_run(
            run_uri,
            metadata={
                "command": "loom run",
                "executor": executor,
                "dry_run": True,
            },
        )

    plan = _persist_slurm_dry_run_plan(
        pipeline_result.spec,
        run_uri=run_uri,
        store=store,
        runtime_options=runtime_options,
    )
    _write_slurm_prepared_run(
        store,
        run_uri=run_uri,
        executor=executor,
        plan=plan,
        runtime_options=runtime_options,
        composed=composed,
    )
    slurm_options = _slurm_options_from_runtime(runtime_options)
    if executor == "slurm-single-job":
        from loom.pipeline.executors.slurm import plan_single_job_slurm_dry_run

        result = plan_single_job_slurm_dry_run(
            run_store=store,
            run_uri=run_uri,
            options=slurm_options,
            resources=None,
        )
    else:
        from loom.pipeline.executors.slurm import plan_afterok_slurm_dry_run

        result = plan_afterok_slurm_dry_run(
            run_store=store,
            run_uri=run_uri,
            options=slurm_options,
            stage_resources=cast(Any, _stage_slurm_resources(runtime_options)),
        )
    return _slurm_dry_run_cli_result(result, warnings=warnings), warnings


def _compose_config(
    config_path: str | Path,
    *,
    overlays: Sequence[str | Path],
    overrides: Sequence[str],
) -> "ComposedConfig":
    from loom.config import compose_config

    return compose_config(config_path, overlays=tuple(overlays), overrides=tuple(overrides))


def _validate_pipeline_config(config: Mapping[str, object]) -> "PipelineValidationResult":
    from loom.pipeline import validate_pipeline_config

    return validate_pipeline_config(config)


def _merge_runtime_options(
    config: Mapping[str, object],
    *,
    run_options: RunCliOptions,
    selector_options: SelectorCliOptions,
    known_stage_ids: Sequence[str],
) -> "RunOptions":
    from loom.pipeline.runtime import merge_config_run_options

    return merge_config_run_options(
        config,
        explicit=run_options.to_runtime_source(selectors=selector_options),
        known_stage_ids=known_stage_ids,
    )


def _with_resolved_run_uri(options: "RunOptions", run_uri: str | None) -> "RunOptions":
    if run_uri is None or options.run_uri == run_uri:
        return options
    from loom.pipeline.runtime import RunOptions

    data = options.to_dict()
    data["run_uri"] = run_uri
    return RunOptions.from_dict(data)


def _create_default_run_store() -> "LocalRunStore":
    from loom.pipeline.stores import LocalRunStore

    return LocalRunStore()


def _resolve_run_uri_for_run(
    store: "LocalRunStore",
    run_uri: str | None,
    *,
    open_existing: bool,
) -> str | None:
    if open_existing and run_uri is None:
        raise CliError(
            "`loom run --resume` requires --run-uri.",
            code="cli.run.resume_requires_run_uri",
            hint="Pass --run-uri or configure runtime.run_uri for strict resume.",
            exit_code=ExitCode.PIPELINE,
        )
    if run_uri is None:
        return store.allocate_run_uri()

    resolved = store.resolve_run_uri(run_uri)
    if open_existing:
        store.open_run(resolved)
    elif store.run_uri_exists(resolved):
        from loom.pipeline.stores import RunAlreadyExistsError

        raise RunAlreadyExistsError(
            f"run URI already exists; use --resume to continue existing state: {resolved}"
        )
    return resolved


def _run_preflight_for_run(
    *,
    config_options: ConfigCliOptions,
    runtime_options: "RunOptions",
    open_existing: bool,
) -> None:
    from loom.diagnostics import PreflightError, PreflightRequest

    if open_existing:
        groups = ("config", "pipeline", "selectors", "runtime", "executor", "resources")
    else:
        groups = ("config", "pipeline", "selectors", "runtime", "run", "executor", "resources")
    try:
        result = _run_diagnostics_preflight(
            PreflightRequest(
                config_path=config_options.config_path,
                groups=groups,
                run_uri=runtime_options.run_uri,
                cwd=Path.cwd(),
                overlays=config_options.overlays,
                overrides=config_options.overrides,
                runtime_options=runtime_options,
            )
        )
    except PreflightError as exc:
        raise CliError(
            f"loom run preflight request failed: {exc}",
            code="cli.run.preflight_request_failed",
            context={"error": str(exc)},
            exit_code=ExitCode.PIPELINE,
        ) from exc

    if _preflight_status_value(result) == "FAIL":
        raise CliError(
            "loom run preflight failed",
            code="cli.run.preflight_failed",
            hint="Run `loom preflight` for detailed diagnostics.",
            context={"status": _preflight_status_value(result)},
            details={"preflight": result.to_dict()},
            exit_code=ExitCode.PIPELINE,
        )


def _run_preflight_for_slurm_dry_run(
    *,
    config_options: ConfigCliOptions,
    runtime_options: "RunOptions",
    open_existing: bool,
) -> "PreflightResult":
    from loom.diagnostics import PreflightError, PreflightRequest

    if open_existing:
        groups = (
            "config",
            "pipeline",
            "selectors",
            "runtime",
            "executor",
            "resources",
            "filesystem",
        )
    else:
        groups = (
            "config",
            "pipeline",
            "selectors",
            "runtime",
            "run",
            "executor",
            "resources",
            "filesystem",
        )
    try:
        result = _run_diagnostics_preflight(
            PreflightRequest(
                config_path=config_options.config_path,
                groups=groups,
                run_uri=runtime_options.run_uri,
                cwd=Path.cwd(),
                overlays=config_options.overlays,
                overrides=config_options.overrides,
                runtime_options=runtime_options,
            )
        )
    except PreflightError as exc:
        raise CliError(
            f"SLURM dry-run preflight request failed: {exc}",
            code="cli.run.slurm_preflight_request_failed",
            context={"error": str(exc)},
            exit_code=ExitCode.PIPELINE,
        ) from exc

    if _preflight_status_value(result) == "FAIL":
        error = CliError(
            "SLURM dry-run preflight failed",
            code="cli.run.slurm_preflight_failed",
            hint="Run `loom preflight --executor "
            f"{runtime_options.executor} --dry-run` for detailed diagnostics.",
            context={"status": _preflight_status_value(result)},
            details={"preflight": result.to_dict()},
            exit_code=ExitCode.PIPELINE,
        )
        error.cli_warnings = _preflight_cli_warnings(result)  # type: ignore[attr-defined]
        raise error
    return result


def _run_diagnostics_preflight(request: "PreflightRequest") -> "PreflightResult":
    from loom.diagnostics import run_preflight

    return run_preflight(request)


def _preflight_status_value(result: object) -> str:
    status = getattr(result, "status")
    return str(getattr(status, "value", status))


def _build_plan_selectors(options: SelectorCliOptions) -> "PlanSelectors":
    from loom.pipeline.planning import PlanSelectors

    return PlanSelectors(
        force_stages=tuple(options.force_stages),
        from_stage=options.from_stage,
        only_stages=tuple(options.only_stages),
        skip_stages=tuple(options.skip_stages),
    )


def _persist_slurm_dry_run_plan(
    spec: "PipelineSpec",
    *,
    run_uri: str,
    store: "LocalRunStore",
    runtime_options: "RunOptions",
) -> "ExecutionPlan":
    from loom.pipeline.planning import ResumeOptions, plan_pipeline
    from loom.pipeline.stores import LocalArtifactStore

    return plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        selectors=runtime_options.to_plan_selectors(),
        resume=ResumeOptions(
            enabled=runtime_options.to_resume_options().enabled,
        ),
        persist=True,
    )


def _write_slurm_prepared_run(
    store: "LocalRunStore",
    *,
    run_uri: str,
    executor: str,
    plan: "ExecutionPlan",
    runtime_options: "RunOptions",
    composed: "ComposedConfig",
) -> None:
    from loom.pipeline.execution import (
        PREPARED_RUN_CONTINUATION_WHOLE_RUN,
        PREPARED_RUN_SCHEMA_VERSION,
        PreparedRunRecord,
    )
    from loom.timestamps import utc_timestamp

    record = PreparedRunRecord(
        schema_version=PREPARED_RUN_SCHEMA_VERSION,
        run_uri=run_uri,
        prepared_at=utc_timestamp(),
        executor_name=executor,
        continuation_type=PREPARED_RUN_CONTINUATION_WHOLE_RUN,
        plan=cast(Mapping[str, "PlainData"], {
            "document_ref": "plan.json",
            "plan_path": "plan.json",
            "plan_summary": dict(plan.summary),
        }),
        config={
            "summary": {
                "source_artifact_count": len(getattr(composed, "source_artifacts", ())),
            }
        },
        runtime=cast(Mapping[str, "PlainData"], {
            "executor": executor,
            "executor_kind": "slurm",
            "stage_count": len(plan.stage_order),
            "resource_summary": _runtime_resource_summary(runtime_options),
            "stage_executor_summary": _stage_executor_summary(runtime_options),
        }),
        metadata={
            "slurm_dry_run": {
                "kind": "loom.slurm_dry_run.prepared",
                "data": {
                    "mode": executor,
                    "dry_run": True,
                    "continuation_type": PREPARED_RUN_CONTINUATION_WHOLE_RUN,
                },
            }
        },
    )
    store.write_prepared_run(run_uri, record.to_dict())


def _slurm_options_from_runtime(runtime_options: "RunOptions") -> "SlurmOptions":
    from loom.pipeline.executors.slurm import SlurmOptions

    raw = runtime_options.adapter_options.get("slurm", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise CliError(
            "SLURM adapter options must be a mapping.",
            code="cli.run.slurm_options_invalid",
            context={"path": "runtime.adapter_options.slurm"},
            exit_code=ExitCode.PIPELINE,
        )
    if not raw:
        return SlurmOptions()
    try:
        return SlurmOptions.from_dict(raw)
    except Exception as exc:  # noqa: BLE001
        raise CliError(
            f"SLURM adapter options are invalid: {exc}",
            code="cli.run.slurm_options_invalid",
            context={"path": "runtime.adapter_options.slurm"},
            exit_code=ExitCode.PIPELINE,
        ) from exc


def _stage_slurm_resources(runtime_options: "RunOptions") -> Mapping[str, object]:
    return {
        stage_id: stage_options.resources
        for stage_id, stage_options in cast(
            Mapping[str, Any],
            runtime_options.stage_options,
        ).items()
    }


def _runtime_resource_summary(runtime_options: "RunOptions") -> dict[str, object]:
    summary: dict[str, object] = {}
    for stage_id, stage_options in cast(Mapping[str, Any], runtime_options.stage_options).items():
        entries = getattr(stage_options.resources, "entries", {})
        if entries:
            summary[stage_id] = sorted(str(kind) for kind in entries)
    return summary


def _stage_executor_summary(runtime_options: "RunOptions") -> dict[str, object]:
    executor = runtime_options.executor or "local"
    return {
        stage_id: executor
        for stage_id in cast(Mapping[str, Any], runtime_options.stage_options)
    }


def _preflight_cli_warnings(result: "PreflightResult") -> tuple[CliWarning, ...]:
    warnings: list[CliWarning] = []
    for check in getattr(result, "checks", ()):
        if _enum_value(getattr(check, "status")) != "WARN":
            continue
        warnings.append(
            CliWarning(
                code=str(getattr(check, "check_id")),
                message=str(getattr(check, "message")),
                details=cast(Mapping[str, object], getattr(check, "details", {})),
            )
        )
    return tuple(warnings)


def _slurm_dry_run_cli_result(
    result: "SlurmDryRunPlanningResult",
    *,
    warnings: tuple[CliWarning, ...],
) -> SlurmDryRunCliResult:
    submission = result.submission
    jobs = tuple(cast(Any, submission).jobs)
    dependencies = tuple(cast(Any, submission).dependencies)
    script_artifacts = result.script_artifacts
    first_script = next(iter(script_artifacts.values()), None)
    script_directory = None if first_script is None else str(first_script.local_path.parent)
    return SlurmDryRunCliResult(
        run_uri=submission.run_uri,
        mode=_enum_value(submission.mode),
        planning_id=submission.planning_id,
        manifest_path=str(result.manifest_artifact.local_path),
        manifest_relative_path=result.manifest_artifact.relative_path,
        plan_path=str(result.plan_artifact.local_path),
        plan_relative_path=result.plan_artifact.relative_path,
        script_directory=script_directory,
        script_count=len(script_artifacts),
        script_paths=tuple(
            {
                "logical_key": logical_key,
                "relative_path": artifact.relative_path,
                "path": str(artifact.local_path),
            }
            for logical_key, artifact in script_artifacts.items()
        ),
        log_paths=tuple(_slurm_log_path_summary(job) for job in jobs),
        job_count=len(jobs),
        dependency_count=len(dependencies),
        generated_commands=tuple(
            {
                "logical_key": getattr(job, "logical_key"),
                "argv": list(getattr(job, "command").argv),
            }
            for job in jobs
        ),
        resource_summary=cast(Mapping[str, object], dict(submission.resources)),
        generated_artifact_count=len(result.generated_artifacts),
        preflight_warnings=tuple(warning.to_dict() for warning in warnings),
    )


def _slurm_log_path_summary(job: object) -> Mapping[str, object]:
    return {
        "logical_key": getattr(job, "logical_key"),
        "stdout_relative_path": getattr(job, "stdout_relative_path"),
        "stderr_relative_path": getattr(job, "stderr_relative_path"),
    }


def _enum_value(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value)


def _is_slurm_executor(executor: object) -> bool:
    return executor in _SLURM_EXECUTORS


def _build_run_request(
    config: "ComposedConfig",
    *,
    open_existing: bool,
    options: "RunOptions",
) -> "RunRequest":
    from loom.pipeline.execution import RunRequest

    return RunRequest(
        config=config,
        open_existing=open_existing,
        options=options,
    )


def _build_executor(executor: str, store: "LocalRunStore") -> "Executor":
    if executor == "local":
        from loom.pipeline.executors import LocalExecutor

        return LocalExecutor()
    if executor == "subprocess":
        from loom.pipeline.executors import SubprocessExecutor

        return SubprocessExecutor(run_store=store)
    raise UnsupportedExecutorError(executor)


def _run_pipeline(
    request: "RunRequest",
    store: "LocalRunStore",
    *,
    executor: "Executor",
) -> "RunResult":
    from loom.pipeline.execution import PipelineRunner

    return PipelineRunner(run_store=store, executor=executor).run(request)


def _run_result_from_execution_result(result: "RunResult") -> RunCliResult:
    return RunCliResult(
        run_uri=result.run_uri,
        status=result.status.value,
        stage_summaries=tuple(
            _stage_summary(stage_name, stage_result)
            for stage_name, stage_result in result.stage_results.items()
        ),
        failure_summary=_failure_summary(result.failure),
        plan_summary=dict(result.plan.summary),
        artifact_count=len(result.artifact_index),
    )


def _stage_summary(stage_name: str, stage_result: object) -> dict[str, object]:
    status = getattr(stage_result, "status")
    failure = getattr(stage_result, "failure")
    return {
        "stage": stage_name,
        "action": getattr(stage_result, "action").value,
        "status": status.value if status is not None else None,
        "attempt": getattr(stage_result, "attempt"),
        "reason_codes": [reason.code.value for reason in getattr(stage_result, "reasons")],
        "output_count": len(getattr(stage_result, "outputs")),
        "failure": _failure_summary(failure),
    }


def _failure_summary(failure: object | None) -> dict[str, object] | None:
    if failure is None:
        return None
    return {
        "stage": getattr(failure, "stage_name"),
        "attempt": getattr(failure, "attempt", None),
        "executor": getattr(failure, "executor", None),
        "failure_type": getattr(failure, "failure_type"),
        "message": getattr(failure, "message"),
        "exception_type": getattr(failure, "exception_type"),
        "exit_code": getattr(failure, "exit_code"),
        "signal": getattr(failure, "signal", None),
        "stdout_path": getattr(failure, "stdout_path", None),
        "stderr_path": getattr(failure, "stderr_path", None),
        "traceback_path": getattr(failure, "traceback_path", None),
        "failure_path": _failure_record_path(failure),
    }


def _failure_record_path(failure: object) -> str | None:
    run_uri = getattr(failure, "run_uri", None)
    stage_name = getattr(failure, "stage_name", None)
    if not isinstance(run_uri, str) or not isinstance(stage_name, str):
        return None
    try:
        from loom.pipeline.stores import LocalRunStore

        return str(LocalRunStore().local_stage_dir(run_uri, stage_name) / "failure.json")
    except Exception:  # noqa: BLE001 - failure path is a best-effort local URI hint.
        return None


__all__ = [
    "RUN_RESULT_SCHEMA_VERSION",
    "SLURM_DRY_RUN_RESULT_SCHEMA_VERSION",
    "SlurmLiveSubmissionDeferredError",
    "UnsupportedExecutorError",
    "build_run_result",
    "build_slurm_dry_run_result",
    "handle",
    "register_subparser",
]
