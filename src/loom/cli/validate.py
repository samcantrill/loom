"""Implementation for ``loom validate``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from loom.cli.formatting import format_json_envelope, format_validation_text
from loom.cli.options import ConfigCliOptions, OutputFormat, ValidateCliOptions, output_format_from_namespace
from loom.cli.results import CliWarning, ValidationCliResult

if TYPE_CHECKING:
    from weave.api import ComposedConfig
    from weave.target_checks import TargetCheckResult
    from loom.pipeline.specs import PipelineSpec
    from loom.pipeline.validation import PipelineTargetCheckResult, PipelineValidationResult


VALIDATE_RESULT_SCHEMA_VERSION = "loom.cli.validate.v2"
TARGET_CHECK_WARNING = CliWarning(
    code="validate.target_constructors_may_run",
    message="--check-targets imports and constructs trusted project targets.",
    details={"consent_boundary": "--check-targets"},
)


def register_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the validate subcommand."""

    parser = subparsers.add_parser("validate", help="validate a pipeline config")
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
    parser.add_argument(
        "--check-targets",
        action="store_true",
        help="instantiate configured targets for an opt-in readiness check",
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
    """Handle ``loom validate``."""

    config_options = ConfigCliOptions.from_namespace(namespace)
    validate_options = ValidateCliOptions.from_namespace(namespace)
    output_format = output_format_from_namespace(namespace)
    warnings: list[CliWarning] = []

    composed = _compose_config(
        config_options.config_path,
        overlays=config_options.overlays,
        overrides=config_options.overrides,
    )
    pipeline_result = _validate_pipeline_config(composed.resolved)
    _validate_runtime_options(
        composed.resolved,
        known_stage_ids=pipeline_result.spec.stage_names,
    )
    target_count: int | None = None

    if validate_options.check_targets:
        warnings.append(TARGET_CHECK_WARNING)
        if output_format is OutputFormat.TEXT:
            _write_text_warnings(warnings)
        try:
            pipeline_target_result = _check_pipeline_stage_targets(pipeline_result.spec)
            generic_target_result = _check_config_targets(
                composed.resolved,
                skip_paths=pipeline_result.stage_factory_target_paths,
            )
        except Exception as exc:
            _attach_cli_warnings(exc, warnings)
            raise
        target_count = pipeline_target_result.target_count + generic_target_result.target_count

    result = ValidationCliResult(
        config_path=config_options.config_path,
        pipeline_name=pipeline_result.pipeline_name,
        stage_count=pipeline_result.stage_count,
        check_targets=validate_options.check_targets,
        target_count=target_count,
    )
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=VALIDATE_RESULT_SCHEMA_VERSION,
                ok=True,
                warnings=warnings,
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_validation_text(result) + "\n")
    return 0


def _compose_config(
    config_path: str | Path,
    *,
    overlays: Sequence[str | Path],
    overrides: Sequence[str],
) -> "ComposedConfig":
    from weave import compose_config

    return compose_config(config_path, overlays=tuple(overlays), overrides=tuple(overrides))


def _validate_pipeline_config(config: Mapping[str, object]) -> "PipelineValidationResult":
    from loom.pipeline import validate_pipeline_config

    return validate_pipeline_config(config)


def _validate_runtime_options(
    config: Mapping[str, object],
    *,
    known_stage_ids: Sequence[str],
) -> None:
    from loom.pipeline.runtime import merge_config_run_options

    merge_config_run_options(config, known_stage_ids=known_stage_ids)


def _check_pipeline_stage_targets(spec: "PipelineSpec") -> "PipelineTargetCheckResult":
    from loom.pipeline import check_pipeline_stage_targets

    return check_pipeline_stage_targets(spec)


def _check_config_targets(config: Mapping[str, object], *, skip_paths: Sequence[str]) -> "TargetCheckResult":
    from weave import check_config_targets

    return check_config_targets(config, skip_paths=tuple(skip_paths))


def _write_text_warnings(warnings: Sequence[CliWarning]) -> None:
    for warning in warnings:
        sys.stderr.write(f"warning: {warning.message}\n")


def _attach_cli_warnings(error: BaseException, warnings: Sequence[CliWarning]) -> None:
    try:
        setattr(error, "cli_warnings", tuple(warnings))
    except Exception:
        pass


__all__ = ["TARGET_CHECK_WARNING", "VALIDATE_RESULT_SCHEMA_VERSION", "handle", "register_subparser"]
