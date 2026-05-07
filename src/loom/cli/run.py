"""Implementation for ``loom run``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope, format_run_text
from loom.cli.options import (
    ConfigCliOptions,
    OutputFormat,
    PlanCliOptions,
    RunCliOptions,
    SelectorCliOptions,
    output_format_from_namespace,
)
from loom.cli.results import RunCliResult

if TYPE_CHECKING:
    from loom.diagnostics import PreflightRequest, PreflightResult
    from loom.config.api import ComposedConfig
    from loom.pipeline.execution import RunRequest, RunResult
    from loom.pipeline.planning import PlanSelectors
    from loom.pipeline.stores import LocalRunStore


RUN_RESULT_SCHEMA_VERSION = "loom.cli.run.v2"


class UnsupportedExecutorError(CliError):
    """Raised when ``loom run`` receives an unsupported executor name."""

    def __init__(self, executor: str) -> None:
        super().__init__(
            f"unsupported executor {executor!r}; v2 supports only 'local'.",
            code="cli.run.unsupported_executor",
            context={"executor": executor, "supported": ["local"]},
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
    parser.add_argument("--executor", default="local", metavar="NAME", help="executor name")
    parser.add_argument("--resume", action="store_true", help="resume an existing run")
    parser.add_argument("--dry-run", action="store_true", help="plan without executing")
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

    if run_options.executor != "local":
        raise UnsupportedExecutorError(run_options.executor)

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
    run_uri = _resolve_run_uri_for_run(store, run_options)
    _run_preflight_for_run(
        config_options=config_options,
        run_options=run_options,
        run_uri=run_uri,
    )
    composed = _compose_config(
        config_options.config_path,
        overlays=config_options.overlays,
        overrides=config_options.overrides,
    )
    request = _build_run_request(
        composed,
        run_uri=run_uri,
        open_existing=run_options.resume,
        selectors=_build_plan_selectors(selector_options),
    )
    result = _run_pipeline(request, store)
    return _run_result_from_execution_result(result)


def _handle_dry_run(
    *,
    config_options: ConfigCliOptions,
    run_options: RunCliOptions,
    selector_options: SelectorCliOptions,
    output_format: OutputFormat,
) -> int:
    from loom.cli.plan import PLAN_RESULT_SCHEMA_VERSION, build_plan_result

    plan_result = build_plan_result(
        config_options=config_options,
        plan_options=PlanCliOptions(
            run_uri=run_options.run_uri,
            resume=run_options.resume,
            explain_stage=None,
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


def _compose_config(
    config_path: str | Path,
    *,
    overlays: Sequence[str | Path],
    overrides: Sequence[str],
) -> "ComposedConfig":
    from loom.config import compose_config

    return compose_config(config_path, overlays=tuple(overlays), overrides=tuple(overrides))


def _create_default_run_store() -> "LocalRunStore":
    from loom.pipeline.stores import LocalRunStore

    return LocalRunStore()


def _resolve_run_uri_for_run(store: "LocalRunStore", options: RunCliOptions) -> str | None:
    if options.resume and options.run_uri is None:
        raise CliError(
            "`loom run --resume` requires --run-uri.",
            code="cli.run.resume_requires_run_uri",
            hint="Pass --run-uri file:///absolute/run for strict resume.",
            exit_code=ExitCode.PIPELINE,
        )
    if options.run_uri is None:
        return store.allocate_run_uri()

    resolved = store.resolve_run_uri(options.run_uri)
    if options.resume:
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
    run_options: RunCliOptions,
    run_uri: str | None,
) -> None:
    from loom.diagnostics import PreflightError, PreflightRequest

    if run_options.resume:
        groups = ("config", "pipeline", "executor")
    else:
        groups = ("config", "pipeline", "run", "executor")
    try:
        result = _run_diagnostics_preflight(
            PreflightRequest(
                config_path=config_options.config_path,
                groups=groups,
                run_uri=run_uri,
                cwd=Path.cwd(),
                overlays=config_options.overlays,
                overrides=config_options.overrides,
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


def _build_run_request(
    config: "ComposedConfig",
    *,
    run_uri: str | None,
    open_existing: bool,
    selectors: "PlanSelectors",
) -> "RunRequest":
    from loom.pipeline.execution import RunRequest
    from loom.pipeline.planning import ResumeOptions

    return RunRequest(
        config=config,
        run_uri=run_uri,
        open_existing=open_existing,
        selectors=selectors,
        resume=ResumeOptions(enabled=open_existing),
    )


def _run_pipeline(request: "RunRequest", store: "LocalRunStore") -> "RunResult":
    from loom.pipeline.execution import PipelineRunner

    return PipelineRunner(run_store=store).run(request)


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
        "failure_type": getattr(failure, "failure_type"),
        "message": getattr(failure, "message"),
        "exception_type": getattr(failure, "exception_type"),
        "exit_code": getattr(failure, "exit_code"),
    }


__all__ = [
    "RUN_RESULT_SCHEMA_VERSION",
    "UnsupportedExecutorError",
    "build_run_result",
    "handle",
    "register_subparser",
]
