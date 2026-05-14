"""Implementation for ``loom sweep`` commands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope
from loom.cli.options import OutputFormat, output_format_from_namespace
from loom.serialization import PlainData

if TYPE_CHECKING:
    from loom.pipeline.execution import RunRequest
    from loom.pipeline.sweep import (
        DirectSweepRunResult,
        QueueSweepDispatchResult,
        SweepCollectionResult,
        SweepPlan,
        SweepPlanPaths,
        SweepStatusSummary,
    )


SWEEP_PLAN_SCHEMA_VERSION = "loom.cli.sweep.plan.v1"
SWEEP_RUN_SCHEMA_VERSION = "loom.cli.sweep.run.v1"
SWEEP_STATUS_SCHEMA_VERSION = "loom.cli.sweep.status.v1"
SWEEP_COLLECT_SCHEMA_VERSION = "loom.cli.sweep.collect.v1"


@dataclass(frozen=True, slots=True)
class SweepPlanCliResult:
    """CLI result for planning a sweep."""

    plan: "SweepPlan"
    sweep_dir: str
    paths: "SweepPlanPaths"

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "sweep_id": self.plan.sweep_id,
            "sweep_dir": self.sweep_dir,
            "trial_count": len(self.plan.trials),
            "provider": self.plan.provider.to_dict(),
            "paths": {
                "sweep_manifest": str(self.paths.sweep_manifest_path),
                "trials_manifest": str(self.paths.trials_manifest_path),
                "authored_spec": str(self.paths.authored_spec_path),
            },
            "trials": [trial.to_dict() for trial in self.plan.trials],
        }


@dataclass(frozen=True, slots=True)
class SweepRunCliResult:
    """CLI result for direct run or queue-backed submission."""

    mode: str
    sweep_id: str
    result: "DirectSweepRunResult | QueueSweepDispatchResult"

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "mode": self.mode,
            "sweep_id": self.sweep_id,
            "result": self.result.to_dict(),
        }


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the sweep command group."""

    parser = subparsers.add_parser("sweep", help="plan, run, and inspect sweeps")
    actions = parser.add_subparsers(dest="sweep_action", metavar="ACTION")
    actions.required = True

    plan = actions.add_parser("plan", help="write deterministic sweep manifests")
    plan.add_argument("spec", metavar="SPEC", help="trusted sweep spec JSON path")
    plan.add_argument("--sweep-dir", required=True, metavar="DIR")
    plan.add_argument("--run-uri-root", metavar="RUN_URI_ROOT")
    _add_output_options(plan)
    plan.set_defaults(handler=handle_plan)

    run = actions.add_parser("run", help="run or enqueue planned sweep trials")
    run.add_argument("spec", metavar="SPEC", help="trusted sweep spec JSON path")
    run.add_argument("--config", required=True, metavar="CONFIG")
    run.add_argument("--sweep-dir", required=True, metavar="DIR")
    run.add_argument("--run-uri-root", metavar="RUN_URI_ROOT")
    run.add_argument("--overlay", action="append", default=None, metavar="PATH")
    run.add_argument(
        "--set",
        dest="override",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="base config override expression applied before trial overrides",
    )
    run.add_argument("--queue-config", metavar="CONFIG")
    run.add_argument("--queue-name", default="default", metavar="QUEUE")
    _add_output_options(run)
    run.set_defaults(handler=handle_run)

    status = actions.add_parser("status", help="summarize sweep trial status")
    status.add_argument("sweep_dir", metavar="SWEEP_DIR")
    status.add_argument("--queue-config", metavar="CONFIG")
    _add_output_options(status)
    status.set_defaults(handler=handle_status)

    collect = actions.add_parser("collect", help="collect sweep metadata and artifact refs")
    collect.add_argument("sweep_dir", metavar="SWEEP_DIR")
    collect.add_argument(
        "--include-unsupported-extraction",
        action="store_true",
        help="include explicit unsupported extraction diagnostics per trial",
    )
    _add_output_options(collect)
    collect.set_defaults(handler=handle_collect)


def handle_plan(namespace: argparse.Namespace) -> int:
    """Handle ``loom sweep plan``."""

    result = build_sweep_plan_result(
        namespace.spec,
        namespace.sweep_dir,
        run_uri_root=namespace.run_uri_root,
    )
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=SWEEP_PLAN_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(_format_sweep_plan_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def handle_run(namespace: argparse.Namespace) -> int:
    """Handle ``loom sweep run``."""

    result = build_sweep_run_result(
        namespace.spec,
        config_path=namespace.config,
        sweep_dir=namespace.sweep_dir,
        run_uri_root=namespace.run_uri_root,
        overlays=tuple(namespace.overlay or ()),
        overrides=tuple(namespace.override or ()),
        queue_config=namespace.queue_config,
        queue_name=namespace.queue_name,
    )
    failed = _enum_value(getattr(result.result, "status", "")) == "failed"
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=SWEEP_RUN_SCHEMA_VERSION,
                ok=not failed,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(_format_sweep_run_text(result) + "\n")
    return int(ExitCode.RUN_FAILED if failed else ExitCode.SUCCESS)


def handle_status(namespace: argparse.Namespace) -> int:
    """Handle ``loom sweep status``."""

    result = build_sweep_status_result(
        namespace.sweep_dir,
        queue_config=namespace.queue_config,
    )
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=SWEEP_STATUS_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(_format_sweep_status_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def handle_collect(namespace: argparse.Namespace) -> int:
    """Handle ``loom sweep collect``."""

    result = build_sweep_collect_result(
        namespace.sweep_dir,
        include_unsupported_extraction=bool(namespace.include_unsupported_extraction),
    )
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=SWEEP_COLLECT_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(_format_sweep_collect_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def build_sweep_plan_result(
    spec_path: str | Path,
    sweep_dir: str | Path,
    *,
    run_uri_root: str | None = None,
) -> SweepPlanCliResult:
    """Plan a sweep and write manifests for CLI use."""

    try:
        from loom.pipeline.sweep import plan_sweep_from_file, write_sweep_plan

        plan = plan_sweep_from_file(spec_path, run_uri_root=run_uri_root)
        paths = write_sweep_plan(plan, sweep_dir)
    except Exception as exc:
        raise _sweep_cli_error(exc) from exc
    return SweepPlanCliResult(plan=plan, sweep_dir=str(sweep_dir), paths=paths)


def build_sweep_run_result(
    spec_path: str | Path,
    *,
    config_path: str | Path,
    sweep_dir: str | Path,
    run_uri_root: str | None = None,
    overlays: Sequence[str | Path] = (),
    overrides: Sequence[str] = (),
    queue_config: str | Path | None = None,
    queue_name: str = "default",
) -> SweepRunCliResult:
    """Run or enqueue a finite sweep through public sweep APIs."""

    try:
        from loom.pipeline.sweep import (
            enqueue_sweep_trials,
            plan_sweep_from_file,
            run_sweep_direct,
        )

        plan = plan_sweep_from_file(spec_path, run_uri_root=run_uri_root)
        template = _build_run_request(
            config_path=config_path,
            overlays=overlays,
            overrides=overrides,
        )
        if queue_config is not None:
            service = _started_queue_service(queue_config)
            result = enqueue_sweep_trials(
                plan,
                queue_service=service,
                queue_name=queue_name,
                request_template=template,
                request_factory=_request_factory(
                    config_path=config_path,
                    overlays=overlays,
                    overrides=overrides,
                ),
                sweep_dir=str(sweep_dir),
            )
            return SweepRunCliResult(
                mode="queue",
                sweep_id=plan.sweep_id,
                result=result,
            )

        runner = _pipeline_runner()
        result = run_sweep_direct(
            plan,
            runner=runner,
            request_template=template,
            request_factory=_request_factory(
                config_path=config_path,
                overlays=overlays,
                overrides=overrides,
            ),
            sweep_dir=str(sweep_dir),
        )
        return SweepRunCliResult(
            mode="direct",
            sweep_id=plan.sweep_id,
            result=result,
        )
    except Exception as exc:
        raise _sweep_cli_error(exc) from exc


def build_sweep_status_result(
    sweep_dir: str | Path,
    *,
    queue_config: str | Path | None = None,
) -> "SweepStatusSummary":
    """Build a sweep status summary from manifests and read models."""

    try:
        from loom.pipeline.sweep import build_sweep_status

        plan = _load_existing_plan(sweep_dir)
        return build_sweep_status(
            plan,
            run_status_reader=_read_run_status,
            queue_items=_queue_items_for_plan(plan, queue_config=queue_config),
        )
    except Exception as exc:
        raise _sweep_cli_error(exc) from exc


def build_sweep_collect_result(
    sweep_dir: str | Path,
    *,
    include_unsupported_extraction: bool = False,
) -> "SweepCollectionResult":
    """Collect sweep metadata and artifact refs from existing manifests."""

    try:
        from loom.pipeline.sweep import collect_sweep_results

        plan = _load_existing_plan(sweep_dir)
        return collect_sweep_results(
            plan,
            run_status_reader=_read_run_status,
            artifact_reader=_read_artifact_index,
            include_unsupported_extraction=include_unsupported_extraction,
        )
    except Exception as exc:
        raise _sweep_cli_error(exc) from exc


def _load_existing_plan(sweep_dir: str | Path) -> "SweepPlan":
    from loom.pipeline.sweep import SweepPlan, read_sweep_plan

    compatibility = read_sweep_plan(sweep_dir)
    if compatibility.diagnostics:
        codes = ", ".join(diagnostic.code for diagnostic in compatibility.diagnostics)
        raise CliError(
            f"incompatible sweep manifests: {codes}",
            code="cli.sweep.incompatible_manifests",
            context={"sweep_dir": str(sweep_dir), "diagnostic_codes": codes},
            exit_code=ExitCode.RUN_STATE,
        )
    if compatibility.sweep_manifest is None or compatibility.trials_manifest is None:
        raise CliError(
            f"sweep manifests not found in {sweep_dir}",
            code="cli.sweep.missing_manifests",
            context={"sweep_dir": str(sweep_dir)},
            exit_code=ExitCode.RUN_STATE,
        )
    return SweepPlan(
        sweep_manifest=compatibility.sweep_manifest,
        trials_manifest=compatibility.trials_manifest,
        authored_spec={},
        provider=compatibility.sweep_manifest.provider,
    )


def _request_factory(
    *,
    config_path: str | Path,
    overlays: Sequence[str | Path],
    overrides: Sequence[str],
) -> Any:
    def factory(trial: object, _dispatch_request: object) -> "RunRequest":
        from loom.pipeline.sweep import trial_override_expressions

        trial_overrides = trial_override_expressions(
            getattr(trial, "proposal_overrides")
        )
        return _build_run_request(
            config_path=config_path,
            overlays=overlays,
            overrides=tuple(overrides) + trial_overrides,
        )

    return factory


def _build_run_request(
    *,
    config_path: str | Path,
    overlays: Sequence[str | Path],
    overrides: Sequence[str],
) -> "RunRequest":
    from loom.pipeline.execution import RunRequest

    path = Path(config_path)
    if not overlays and path.suffix.lower() == ".json":
        from loom.config.overrides import apply_overrides, parse_overrides
        from loom.serialization import json_loads

        payload = json_loads(path.read_text(encoding="utf-8"), path=str(path))
        if not isinstance(payload, Mapping):
            raise CliError(
                "JSON pipeline config must contain an object",
                code="cli.sweep.invalid_config",
                context={"config_path": str(path)},
                exit_code=ExitCode.CONFIG,
            )
        config = apply_overrides(
            cast(Mapping[str, PlainData], payload),
            parse_overrides(tuple(overrides)),
        )
        return RunRequest(config=config)

    from loom.config import compose_config

    return RunRequest(
        config=compose_config(
            config_path,
            overlays=tuple(overlays),
            overrides=tuple(overrides),
        )
    )


def _pipeline_runner() -> object:
    from loom.pipeline.execution import PipelineRunner
    from loom.pipeline.execution import create_offline_evidence_run_store

    return PipelineRunner(
        run_store=create_offline_evidence_run_store(
            "runs",
            owner_id="sweep-cli",
        )
    )


def _started_queue_service(config_path: str | Path) -> object:
    from loom.queue import QueueService, load_queue_spec

    path = Path(config_path)
    if path.suffix.lower() == ".json":
        from loom.queue import normalize_queue_spec
        from loom.serialization import json_loads

        spec = normalize_queue_spec(
            json_loads(path.read_text(encoding="utf-8"), path=str(path))
        )
    else:
        spec = load_queue_spec(path)
    service = QueueService.from_spec(spec)
    service.start()
    return service


def _queue_items_for_plan(
    plan: "SweepPlan",
    *,
    queue_config: str | Path | None,
) -> tuple[object, ...]:
    if queue_config is None:
        return ()
    from loom.pipeline.sweep import build_queue_item_id

    service = _started_queue_service(queue_config)
    read_item = getattr(service, "read_item")
    items: list[object] = []
    for trial in plan.trials:
        item = read_item(build_queue_item_id(plan.sweep_id, trial.trial_id))
        if item is not None:
            items.append(item)
    return tuple(items)


def _read_run_status(run_uri: str) -> object | None:
    from loom.pipeline.stores import LocalRunStore

    try:
        return LocalRunStore().read_run_status(run_uri)
    except Exception:
        return None


def _read_artifact_index(run_uri: str) -> Mapping[str, object] | None:
    from loom.pipeline.stores import LocalRunStore

    try:
        return LocalRunStore().read_artifact_index(run_uri)
    except Exception as exc:
        raise CliError(
            str(exc),
            code="cli.sweep.artifact_read_error",
            context={"run_uri": run_uri, "error_type": type(exc).__name__},
            exit_code=ExitCode.RUN_STATE,
        ) from exc


def _format_sweep_plan_text(result: SweepPlanCliResult) -> str:
    lines = [
        f"sweep: {result.plan.sweep_id}",
        f"trials: {len(result.plan.trials)}",
        f"sweep_dir: {result.sweep_dir}",
    ]
    for trial in result.plan.trials:
        lines.append(f"- {trial.trial_id}: {trial.run_uri}")
    return "\n".join(lines)


def _format_sweep_run_text(result: SweepRunCliResult) -> str:
    aggregate = result.result
    lines = [
        f"sweep: {result.sweep_id}",
        f"mode: {result.mode}",
        f"status: {_enum_value(getattr(aggregate, 'status', 'unknown'))}",
        f"trials: {getattr(aggregate, 'trial_count', 0)}",
    ]
    if result.mode == "queue":
        lines.append(f"submitted: {getattr(aggregate, 'submitted_count', 0)}")
    else:
        lines.append(f"succeeded: {getattr(aggregate, 'succeeded_count', 0)}")
    lines.append(f"failed: {getattr(aggregate, 'failed_count', 0)}")
    return "\n".join(lines)


def _format_sweep_status_text(result: "SweepStatusSummary") -> str:
    lines = [
        f"sweep: {result.sweep_id}",
        f"status: {result.status.value}",
        f"trials: {result.trial_count}",
    ]
    counts = {key: value for key, value in result.counts.items() if value}
    if counts:
        lines.append(
            "counts: "
            + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        )
    for trial in result.trials:
        lines.append(f"- {trial.trial_id}: {trial.outcome.value} ({trial.run_uri})")
    return "\n".join(lines)


def _format_sweep_collect_text(result: "SweepCollectionResult") -> str:
    lines = [
        f"sweep: {result.sweep_id}",
        f"trials: {result.trial_count}",
        f"artifacts: {result.artifact_count}",
    ]
    if result.diagnostics:
        lines.append(f"diagnostics: {len(result.diagnostics)}")
    for trial in result.trials:
        lines.append(
            f"- {trial.trial_id}: {trial.status.outcome.value}, "
            f"artifacts={trial.artifact_count}"
        )
    return "\n".join(lines)


def _add_output_options(parser: argparse.ArgumentParser) -> None:
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


def _sweep_cli_error(error: BaseException) -> CliError:
    if isinstance(error, CliError):
        return error
    return CliError(
        str(error),
        code="cli.sweep.operation_error",
        context={"error_type": type(error).__name__},
        exit_code=ExitCode.RUN_STATE,
    )


def _enum_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else str(raw)


__all__ = [
    "SWEEP_COLLECT_SCHEMA_VERSION",
    "SWEEP_PLAN_SCHEMA_VERSION",
    "SWEEP_RUN_SCHEMA_VERSION",
    "SWEEP_STATUS_SCHEMA_VERSION",
    "SweepPlanCliResult",
    "SweepRunCliResult",
    "build_sweep_collect_result",
    "build_sweep_plan_result",
    "build_sweep_run_result",
    "build_sweep_status_result",
    "handle_collect",
    "handle_plan",
    "handle_run",
    "handle_status",
    "register_subparser",
]
