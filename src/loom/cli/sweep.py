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
from loom.serialization import PlainData, thaw_plain_data

if TYPE_CHECKING:
    from loom.pipeline.sweep import (
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
    """CLI result for native sweep execution."""

    sweep_id: str
    result: "SweepStatusSummary"

    def to_dict(self) -> dict[str, PlainData]:
        return {
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

    run = actions.add_parser("run", help="run planned trials through native operations")
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
    run.add_argument("--deployment", required=True, metavar="CONFIG")
    run.add_argument("--no-wait", action="store_true")
    run.add_argument("--timeout", type=float, default=None)
    _add_output_options(run)
    run.set_defaults(handler=handle_run)

    status = actions.add_parser("status", help="summarize sweep trial status")
    status.add_argument("sweep_dir", metavar="SWEEP_DIR")
    status.add_argument("--deployment", metavar="CONFIG")
    _add_output_options(status)
    status.set_defaults(handler=handle_status)

    collect = actions.add_parser(
        "collect", help="collect sweep metadata and artifact refs"
    )
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
        deployment=namespace.deployment,
        wait=not namespace.no_wait,
        timeout_seconds=namespace.timeout,
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
        deployment=namespace.deployment,
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
    deployment: str | Path,
    run_uri_root: str | None = None,
    overlays: Sequence[str | Path] = (),
    overrides: Sequence[str] = (),
    wait: bool = True,
    timeout_seconds: float | None = None,
) -> SweepRunCliResult:
    """Compose serialized trial intent; preparation happens at the selected service."""
    try:
        from loom.coordinator import RunRequest
        from loom.deployment import load_deployment
        from loom.queue.preparation import PrepareRunRequest
        from loom.pipeline.sweep import plan_sweep_from_file, run_sweep

        selection = load_deployment(deployment)
        plan = plan_sweep_from_file(spec_path, run_uri_root=run_uri_root)
        template = RunRequest(
            PrepareRunRequest(
                "sweep-template",
                "sweep-template",
                selection.source,
                str(config_path),
                selection.preparation_profile,
                tuple(map(str, overlays)),
                tuple(overrides),
            ),
            "sweep-template",
        )
        result = run_sweep(
            plan,
            request_template=template,
            deployment=deployment,
            sweep_dir=sweep_dir,
            wait=wait,
            timeout_seconds=timeout_seconds,
        )
        return SweepRunCliResult(sweep_id=plan.sweep_id, result=result)
    except Exception as exc:
        raise _sweep_cli_error(exc) from exc


def build_sweep_status_result(
    sweep_dir: str | Path,
    *,
    deployment: str | Path | None = None,
) -> "SweepStatusSummary":
    """Read retained facts, optionally refreshing native operation observations."""
    try:
        from loom.pipeline.sweep import build_sweep_status, observe_sweep

        plan = _load_existing_plan(sweep_dir)
        if deployment is None:
            return build_sweep_status(plan, run_status_reader=_read_run_status)
        from loom.deployment import ensure_available, load_deployment
        from uuid import uuid4

        available = ensure_available(
            load_deployment(deployment), attachment_id="sweep-observe-" + uuid4().hex
        )
        try:
            return observe_sweep(plan, client=available.client, sweep_dir=sweep_dir)
        finally:
            available.release()
            available.client.close()
    except Exception as exc:
        raise _sweep_cli_error(exc) from exc


def build_sweep_collect_result(
    sweep_dir: str | Path,
    *,
    include_unsupported_extraction: bool = False,
) -> "SweepCollectionResult":
    """Collect native committed refs through the retained deployment's authority view.

    Native collection may reopen the selected service for readback. It never
    submits runs and does not require a legacy materialized artifact index.
    """
    available = None
    try:
        from loom.pipeline.sweep import collect_sweep_results
        from loom.artifacts import ArtifactRef
        from loom.deployment import ensure_available, load_deployment
        from uuid import uuid4

        plan = _load_existing_plan(sweep_dir)
        records = cast(
            dict[str, Any], plan.sweep_manifest.metadata.get("native_runs", {})
        )
        by_uri = {
            trial.run_uri: records[trial.trial_id]
            for trial in plan.trials
            if trial.trial_id in records
        }

        def read_artifacts(run_uri: str):
            nonlocal available
            record = by_uri.get(run_uri)
            if record is None:
                return {} if records else _read_artifact_index(run_uri)
            if available is None:
                available = ensure_available(
                    load_deployment(record["deployment"]),
                    attachment_id="sweep-collect-" + uuid4().hex,
                )
            observation = record.get("observation") or {}
            operation = observation.get("operation") or {}
            if not observation.get("admission") and operation.get("state") in {
                "failed",
                "cancelled",
                "conflict",
            }:
                return {}
            owner = (observation.get("connection") or {}).get("coordinator_id")
            admission = available.client.admission_for_queue_item(
                record["request"]["queue_item_id"], expected_coordinator_id=owner
            )
            detail = available.client.admission(
                admission.admission_id, expected_coordinator_id=owner
            )
            if detail.authority.get("availability") != "available":
                raise ValueError("native artifact authority is unavailable")
            artifacts = cast(dict[str, Any], detail.authority["artifacts"])
            return {
                key: ArtifactRef.from_dict(thaw_plain_data(value)) for key, value in artifacts.items()
            }

        return collect_sweep_results(
            plan,
            run_status_reader=_read_run_status,
            artifact_reader=read_artifacts,
            include_unsupported_extraction=include_unsupported_extraction,
        )
    except Exception as exc:
        raise _sweep_cli_error(exc) from exc
    finally:
        if available is not None:
            available.release()
            available.client.close()


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
        f"status: {_enum_value(getattr(aggregate, 'status', 'unknown'))}",
        f"trials: {getattr(aggregate, 'trial_count', 0)}",
    ]
    lines.append(f"succeeded: {aggregate.succeeded_count}")
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
