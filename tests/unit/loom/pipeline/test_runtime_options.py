"""Unit tests for runtime option and environment models."""

from __future__ import annotations

from typing import Any, cast

import pytest

from loom.pipeline import (
    ExecutionOptions,
    ResourceEntry,
    ResourceRequest,
    RunEnvironmentRequest,
    RunOptions,
    StageEnvironmentRequest,
    StageRuntimeOptions,
    parse_run_options,
    validate_stage_runtime_options,
)
from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.planning.models import PlanSelectors, ResumeOptions
from loom.pipeline.runtime import RUN_OPTIONS_SCHEMA_VERSION


def test_run_options_defaults_round_trip() -> None:
    options = RunOptions()

    assert options.to_dict() == {
        "schema_version": RUN_OPTIONS_SCHEMA_VERSION,
        "run_uri": None,
        "executor": None,
        "dry_run": False,
        "profile": None,
        "tags": {},
        "notes": [],
        "selectors": {
            "force_stages": [],
            "from_stage": None,
            "only_stages": [],
            "skip_stages": [],
        },
        "resume": {"enabled": True},
        "execution": {"settings": {}},
        "stage_options": {},
        "environment": {
            "inherit": True,
            "set_variables": {},
            "unset_variables": [],
        },
        "adapter_options": {},
    }
    assert RunOptions.from_dict(options.to_dict()) == options
    assert parse_run_options(None) == options


def test_run_options_populated_round_trip_freezes_inputs_and_sorts_mappings() -> None:
    tags = {"z": "last", "a": "first"}
    adapter_options: dict[str, Any] = {"slurm": {"partition": "debug"}}
    stage_env = {
        "inherit": False,
        "set_variables": {"TOKEN": "secret", "PATH": "/tmp/bin"},
        "unset_variables": ["OLD_SECRET"],
    }
    options = RunOptions(
        run_uri="runs/demo",
        executor="local",
        dry_run=True,
        profile="debug",
        tags=tags,
        notes=["created by test"],
        selectors={"only_stages": ["train"], "force_stages": ["extract"]},
        resume={"enabled": False},
        execution={"settings": {"mode": "plan"}},
        stage_options={
            "train": {
                "resources": {
                    "entries": {
                        "cpu": {"kind": "cpu", "amount": 2},
                        "memory": {"kind": "memory", "amount": 4, "unit": "GiB"},
                    }
                },
                "execution": {"settings": {"queue": "short"}},
                "environment": stage_env,
                "adapter_options": adapter_options,
            }
        },
        environment={
            "set_variables": {"RUN_TOKEN": "run-secret"},
            "unset_variables": ["LEGACY_SECRET"],
        },
        adapter_options={"local": {"dry_run_reason": "inspection"}},
    )
    tags["a"] = "mutated"
    adapter_options["slurm"] = {"partition": "mutated"}

    assert options.tags == {"a": "first", "z": "last"}
    assert options.to_plan_selectors() == PlanSelectors(
        force_stages=("extract",),
        only_stages=("train",),
    )
    assert options.to_resume_options() == ResumeOptions(enabled=False)
    assert RunOptions.from_dict(options.to_dict()) == options
    with pytest.raises(TypeError):
        cast(Any, options.tags)["a"] = "changed"
    with pytest.raises(TypeError):
        cast(Any, options.adapter_options)["local"] = {}


def test_safe_metadata_omits_environment_keys_values_and_raw_adapter_payloads() -> None:
    options = RunOptions(
        adapter_options={"slurm": {"account": "sensitive-account"}},
        environment={
            "set_variables": {"API_TOKEN": "secret-value"},
            "unset_variables": ["OLD_TOKEN"],
        },
        stage_options={
            "train": StageRuntimeOptions(
                resources=ResourceRequest(
                    entries={"cpu": ResourceEntry(kind="cpu", amount=2)}
                ),
                environment=StageEnvironmentRequest(
                    set_variables={"STAGE_SECRET": "stage-secret"},
                    unset_variables=["STAGE_OLD_SECRET"],
                ),
                adapter_options={"docker": {"env_file": ".env"}},
            )
        },
    )

    summary = options.to_safe_metadata()
    summary_text = repr(summary)
    assert "API_TOKEN" not in summary_text
    assert "secret-value" not in summary_text
    assert "OLD_TOKEN" not in summary_text
    assert "STAGE_SECRET" not in summary_text
    assert "stage-secret" not in summary_text
    assert "STAGE_OLD_SECRET" not in summary_text
    assert "sensitive-account" not in summary_text
    assert ".env" not in summary_text
    assert summary["environment"] == {
        "inherit": True,
        "set_variable_count": 1,
        "unset_variable_count": 1,
    }
    assert summary["adapter_options"] == {
        "namespace_count": 1,
        "namespaces": ["slurm"],
    }


@pytest.mark.parametrize(
    "factory",
    [
        lambda: RunOptions.from_dict({"unknown": True}),
        lambda: ExecutionOptions.from_dict({"timeout_seconds": 5}),
        lambda: StageRuntimeOptions.from_dict({"retry": {"attempts": 2}}),
        lambda: RunEnvironmentRequest.from_dict({"env": {"TOKEN": "secret"}}),
        lambda: StageEnvironmentRequest.from_dict({"set_variables": {"BAD=KEY": "x"}}),
    ],
)
def test_runtime_options_reject_unknown_and_invalid_fields(factory: Any) -> None:
    with pytest.raises(RuntimeResourceError):
        factory()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: RunOptions(run_uri=""),
        lambda: RunOptions(executor=""),
        lambda: RunOptions(dry_run="yes"),  # type: ignore[arg-type]
        lambda: RunOptions(profile=""),
        lambda: RunOptions(tags={"team": 1}),  # type: ignore[dict-item]
        lambda: RunOptions(notes="single note"),
        lambda: RunOptions(stage_options={"bad.stage": StageRuntimeOptions()}),
        lambda: RunEnvironmentRequest(unset_variables=["TOKEN", "TOKEN"]),
    ],
)
def test_runtime_options_reject_invalid_scalars(factory: Any) -> None:
    with pytest.raises(RuntimeResourceError):
        factory()


def test_stage_runtime_options_use_entry_based_resources_only() -> None:
    options = StageRuntimeOptions(
        resources={
            "entries": {
                "gpu": {"kind": "gpu", "amount": 0},
            }
        }
    )

    assert cast(ResourceRequest, options.resources).entries["gpu"] == ResourceEntry(
        kind="gpu",
        amount=0,
    )
    with pytest.raises(RuntimeResourceError):
        StageRuntimeOptions(resources={"cpus": 2})


def test_validate_stage_runtime_options_checks_supplied_known_stage_ids() -> None:
    options = RunOptions(stage_options={"extract": StageRuntimeOptions()})

    validate_stage_runtime_options(options, known_stage_ids={"extract", "train"})
    with pytest.raises(RuntimeResourceError, match="unknown stage id"):
        validate_stage_runtime_options(options, known_stage_ids={"train"})
