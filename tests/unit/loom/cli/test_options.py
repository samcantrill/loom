"""Unit tests for CLI option adapters."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from loom.cli.options import (
    ConfigCliOptions,
    OutputFormat,
    PlanCliOptions,
    RunCliOptions,
    SelectorCliOptions,
    ValidateCliOptions,
    output_format_from_namespace,
)


pytestmark = pytest.mark.unit


def test_output_format_parses_supported_values() -> None:
    assert OutputFormat.parse("text") is OutputFormat.TEXT
    assert OutputFormat.parse("json") is OutputFormat.JSON
    assert OutputFormat.parse(OutputFormat.TEXT) is OutputFormat.TEXT


def test_output_format_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="Unknown output format"):
        OutputFormat.parse("yaml")


def test_option_adapters_normalize_argparse_namespaces() -> None:
    namespace = Namespace(
        config="pipeline.yaml",
        overlay=["team.yaml"],
        override=["a.b=1"],
        from_stage="prepare",
        only_stage=["train"],
        force_stage=["score"],
        skip_stage=["publish"],
        check_targets=True,
        run_uri="file://./runs/example",
        resume=True,
        explain_stage="train",
        executor="local",
        dry_run=True,
        output_format="json",
    )

    assert ConfigCliOptions.from_namespace(namespace) == ConfigCliOptions(
        config_path=Path("pipeline.yaml"),
        overlays=(Path("team.yaml"),),
        overrides=("a.b=1",),
    )
    assert SelectorCliOptions.from_namespace(namespace) == SelectorCliOptions(
        from_stage="prepare",
        only_stages=frozenset({"train"}),
        force_stages=frozenset({"score"}),
        skip_stages=frozenset({"publish"}),
    )
    assert ValidateCliOptions.from_namespace(namespace) == ValidateCliOptions(check_targets=True)
    assert PlanCliOptions.from_namespace(namespace) == PlanCliOptions(
        run_uri="file://./runs/example",
        resume=True,
        explain_stage="train",
    )
    assert RunCliOptions.from_namespace(namespace) == RunCliOptions(
        run_uri="file://./runs/example",
        executor="local",
        resume=True,
        dry_run=True,
    )
    assert output_format_from_namespace(namespace) is OutputFormat.JSON
