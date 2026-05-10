"""Implementation for ``loom plan``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope, format_plan_text
from loom.cli.options import (
    ConfigCliOptions,
    OutputFormat,
    PlanCliOptions,
    SelectorCliOptions,
    output_format_from_namespace,
)
from loom.cli.results import PlanCliResult

if TYPE_CHECKING:
    from loom.config.api import ComposedConfig
    from loom.pipeline.planning import ExecutionPlan, PlanSelectors, StageExplanation
    from loom.pipeline.runtime import RunOptions
    from loom.pipeline.specs import PipelineSpec
    from loom.pipeline.stores import LocalRunStore
    from loom.pipeline.stores.artifact_store import ArtifactStore
    from loom.pipeline.stores.run_store import LegacyRunStore as RunStore
    from loom.pipeline.validation import PipelineValidationResult


PLAN_RESULT_SCHEMA_VERSION = "loom.cli.plan.v2"
_HYPOTHETICAL_PLAN_RUN_URI = "file:///__loom_plan_hypothetical__"


class _UnavailableRunStore:
    """Run-store sentinel for fresh read-only planning."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"fresh planning must not inspect run state via {name}")


class _UnavailableArtifactStore:
    """Artifact-store sentinel for fresh read-only planning."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"fresh planning must not inspect artifacts via {name}")


def register_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the plan subcommand."""

    parser = subparsers.add_parser("plan", help="plan a pipeline run")
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
    parser.add_argument(
        "--profile",
        dest="runtime_profile",
        metavar="NAME",
        help="runtime profile to select",
    )
    parser.add_argument(
        "--executor",
        dest="runtime_executor",
        default=None,
        metavar="NAME",
        help="executor name",
    )
    parser.add_argument("--resume", action="store_true", help="resume an existing run")
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
    parser.add_argument("--explain", dest="explain_stage", metavar="STAGE", help="explain a planned stage")
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
    """Handle ``loom plan``."""

    config_options = ConfigCliOptions.from_namespace(namespace)
    plan_options = PlanCliOptions.from_namespace(namespace)
    selector_options = SelectorCliOptions.from_namespace(namespace)
    output_format = output_format_from_namespace(namespace)

    result = build_plan_result(
        config_options=config_options,
        plan_options=plan_options,
        selector_options=selector_options,
    )
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=PLAN_RESULT_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_plan_text(result) + "\n")
    return 0


def build_plan_result(
    *,
    config_options: ConfigCliOptions,
    plan_options: PlanCliOptions,
    selector_options: SelectorCliOptions,
) -> PlanCliResult:
    """Build the CLI-specific plan view."""

    store = _create_default_run_store()
    composed = _compose_config(
        config_options.config_path,
        overlays=config_options.overlays,
        overrides=config_options.overrides,
    )
    pipeline_result = _validate_pipeline_config(composed.resolved)
    runtime_options = _merge_runtime_options(
        composed.resolved,
        plan_options=plan_options,
        selector_options=selector_options,
        known_stage_ids=pipeline_result.spec.stage_names,
    )
    run_uri = _resolve_run_uri_for_plan(
        store,
        runtime_options.run_uri,
        open_existing=plan_options.resume,
    )
    selectors = runtime_options.to_plan_selectors()
    resume_enabled = (
        plan_options.resume
        and runtime_options.to_resume_options().enabled
        and run_uri is not None
    )
    run_store, artifact_store, planner_run_uri = _stores_for_plan(store, run_uri)
    plan = _plan_pipeline(
        pipeline_result.spec,
        run_uri=planner_run_uri,
        run_store=run_store,
        artifact_store=artifact_store,
        selectors=selectors,
        resume_enabled=resume_enabled,
    )
    explanation = _explanation_payload(plan, plan_options.explain_stage)
    return _plan_result_from_execution_plan(
        config_path=config_options.config_path,
        display_run_uri=run_uri,
        resume=resume_enabled,
        plan=plan,
        explanation=explanation,
    )


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
    plan_options: PlanCliOptions,
    selector_options: SelectorCliOptions,
    known_stage_ids: Sequence[str],
) -> "RunOptions":
    from loom.pipeline.runtime import merge_config_run_options

    return merge_config_run_options(
        config,
        explicit=plan_options.to_runtime_source(selectors=selector_options),
        known_stage_ids=known_stage_ids,
    )


def _build_plan_selectors(options: SelectorCliOptions) -> "PlanSelectors":
    from loom.pipeline.planning import PlanSelectors

    return PlanSelectors(
        force_stages=tuple(options.force_stages),
        from_stage=options.from_stage,
        only_stages=tuple(options.only_stages),
        skip_stages=tuple(options.skip_stages),
    )


def _create_default_run_store() -> "LocalRunStore":
    from loom.pipeline.stores import LocalRunStore

    return LocalRunStore()


def _resolve_run_uri_for_plan(
    store: "LocalRunStore",
    run_uri: str | None,
    *,
    open_existing: bool,
) -> str | None:
    if open_existing and run_uri is None:
        raise CliError(
            "`loom plan --resume` requires --run-uri.",
            code="cli.plan.resume_requires_run_uri",
            hint="Pass --run-uri or configure runtime.run_uri for strict resume.",
            exit_code=ExitCode.PIPELINE,
        )
    if run_uri is None:
        return None

    resolved = store.resolve_run_uri(run_uri)
    if open_existing:
        store.open_run(resolved)
    elif store.run_uri_exists(resolved):
        from loom.pipeline.stores import RunAlreadyExistsError

        raise RunAlreadyExistsError(
            f"run URI already exists; use --resume to inspect existing state: {resolved}"
        )
    return resolved


def _stores_for_plan(
    store: "LocalRunStore", run_uri: str | None
) -> tuple["RunStore", "ArtifactStore", str]:
    if run_uri is None:
        return (
            cast("RunStore", _UnavailableRunStore()),
            cast("ArtifactStore", _UnavailableArtifactStore()),
            _HYPOTHETICAL_PLAN_RUN_URI,
        )

    from loom.pipeline.stores import LocalArtifactStore

    return (
        cast("RunStore", store),
        LocalArtifactStore(store.local_artifact_root(run_uri)),
        run_uri,
    )


def _plan_pipeline(
    spec: "PipelineSpec",
    *,
    run_uri: str,
    run_store: "RunStore",
    artifact_store: "ArtifactStore",
    selectors: "PlanSelectors",
    resume_enabled: bool,
) -> "ExecutionPlan":
    from loom.pipeline.planning import ResumeOptions, plan_pipeline

    return plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=artifact_store,
        selectors=selectors,
        resume=ResumeOptions(enabled=resume_enabled),
        persist=False,
    )


def _explanation_payload(plan: "ExecutionPlan", explain_stage: str | None) -> dict[str, object] | None:
    if explain_stage is None:
        return None

    from loom.pipeline.planning import explain_plan

    explanation = explain_plan(plan)
    by_stage: dict[str, StageExplanation] = {
        stage.stage_name: stage for stage in explanation.stage_explanations
    }
    stage = by_stage.get(explain_stage)
    if stage is None:
        raise CliError(
            f"cannot explain unknown planned stage {explain_stage!r}",
            code="cli.plan.unknown_explain_stage",
            context={"stage": explain_stage},
            exit_code=ExitCode.PIPELINE,
        )
    payload = stage.to_dict()
    return _stage_explanation_view(payload)


def _plan_result_from_execution_plan(
    *,
    config_path: Path,
    display_run_uri: str | None,
    resume: bool,
    plan: "ExecutionPlan",
    explanation: Mapping[str, object] | None,
) -> PlanCliResult:
    return PlanCliResult(
        config_path=config_path,
        pipeline_name=plan.pipeline_name,
        run_uri=display_run_uri,
        resume=resume,
        selectors=plan.selectors.to_dict(),
        summary=dict(plan.summary),
        stage_actions=tuple(_stage_action_view(stage) for stage in plan.ordered_stage_plans),
        explanation=explanation,
    )


def _stage_action_view(stage: object) -> dict[str, object]:
    reason_codes = [reason.code.value for reason in getattr(stage, "reasons")]
    return {
        "stage": getattr(stage, "stage_name"),
        "action": getattr(stage, "action").value,
        "base_action": getattr(stage, "base_action").value,
        "fingerprint_status": getattr(stage, "fingerprint_status").value,
        "reason_codes": _dedupe_strings(reason_codes),
        "reasons": [reason.to_dict() for reason in getattr(stage, "reasons")],
        "pending_inputs": [item.to_dict() for item in getattr(stage, "pending_inputs")],
        "reusable_outputs": {
            name: ref.to_dict() for name, ref in getattr(stage, "reusable_outputs").items()
        },
        "upstream_stages": list(getattr(stage, "upstream_stages")),
        "downstream_stages": list(getattr(stage, "downstream_stages")),
    }


def _stage_explanation_view(payload: Mapping[str, object]) -> dict[str, object]:
    reason_codes = payload["reason_codes"]
    return {
        "stage": payload["stage_name"],
        "action": payload["action"],
        "base_action": payload["base_action"],
        "fingerprint_status": payload["fingerprint_status"],
        "reason_codes": _dedupe_strings(reason_codes if isinstance(reason_codes, Sequence) else ()),
        "reasons": payload["reasons"],
        "selector_reasons": payload["selector_reasons"],
        "invalidation_reasons": payload["invalidation_reasons"],
        "resume_reasons": payload["resume_reasons"],
        "pending_inputs": payload["pending_inputs"],
        "bound_inputs": payload["bound_inputs"],
        "reusable_outputs": payload["reusable_outputs"],
        "upstream_stages": payload["upstream_stages"],
        "downstream_stages": payload["downstream_stages"],
        "prior_fingerprint": payload["prior_fingerprint"],
        "current_fingerprint": payload["current_fingerprint"],
    }


def _dedupe_strings(values: Sequence[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


__all__ = ["PLAN_RESULT_SCHEMA_VERSION", "build_plan_result", "handle", "register_subparser"]
