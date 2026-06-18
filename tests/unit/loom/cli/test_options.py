"""Unit tests for CLI option adapters."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from loom.cli.options import (
    ConfigCliOptions,
    OutputFormat,
    PlanCliOptions,
    PreflightCliOptions,
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
        runtime_executor="slurm",
        runtime_profile="cluster",
        dry_run=True,
        max_parallel_stages=3,
        failure_policy="continue-independent",
        tag=["team=platform", "owner=cli"],
        note=["first", "second"],
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
        profile="cluster",
        executor="slurm",
        tags=(("team", "platform"), ("owner", "cli")),
        notes=("first", "second"),
        explain_stage="train",
    )
    assert PreflightCliOptions.from_namespace(namespace) == PreflightCliOptions(
        run_uri="file://./runs/example",
        executor="slurm",
        profile="cluster",
        dry_run=True,
        resume=True,
        tags=(("team", "platform"), ("owner", "cli")),
        notes=("first", "second"),
    )
    assert RunCliOptions.from_namespace(namespace) == RunCliOptions(
        run_uri="file://./runs/example",
        executor="local",
        resume=True,
        dry_run=True,
        max_parallel_stages=3,
        failure_policy="continue_independent",
        tags=(("team", "platform"), ("owner", "cli")),
        notes=("first", "second"),
    )
    assert output_format_from_namespace(namespace) is OutputFormat.JSON


def test_runtime_cli_options_build_sparse_runtime_sources() -> None:
    selectors = SelectorCliOptions(
        from_stage="prepare",
        only_stages=frozenset({"train"}),
    )
    plan_options = PlanCliOptions(
        run_uri="file:///runs/demo",
        profile="cluster",
        executor="local",
        tags=(("team", "platform"),),
        notes=("review",),
    )
    run_options = RunCliOptions(
        dry_run=True,
        max_parallel_stages=4,
        failure_policy="continue_independent",
    )

    assert plan_options.to_runtime_source(selectors=selectors) == {
        "run_uri": "file:///runs/demo",
        "executor": "local",
        "profile": "cluster",
        "tags": {"team": "platform"},
        "notes": ["review"],
        "selectors": {
            "from_stage": "prepare",
            "only_stages": ["train"],
        },
    }
    assert run_options.to_runtime_source() == {
        "dry_run": True,
        "execution": {
            "settings": {
                "failure_policy": "continue_independent",
                "max_parallel_stages": 4,
            }
        },
    }


def test_runtime_cli_tag_and_note_validation() -> None:
    with pytest.raises(ValueError, match="KEY=VALUE"):
        PreflightCliOptions.from_namespace(Namespace(tag=["bad"], note=[]))
    with pytest.raises(ValueError, match="key must be non-empty"):
        PreflightCliOptions.from_namespace(Namespace(tag=["=value"], note=[]))
    with pytest.raises(ValueError, match="non-empty string"):
        PreflightCliOptions.from_namespace(Namespace(tag=[], note=[""]))
