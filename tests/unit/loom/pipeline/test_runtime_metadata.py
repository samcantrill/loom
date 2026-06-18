"""Unit tests for safe runtime metadata and resolved stage runtime."""

from __future__ import annotations

from typing import cast

import pytest

from loom.pipeline import ResourceEntry, ResourceRequest
from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.reliability import ReliabilityPolicy, RetryPolicy, TimeoutPolicy
from loom.pipeline.runtime import (
    RUNTIME_METADATA_SCHEMA_VERSION,
    ExecutionOptions,
    RunOptions,
    ResolvedStageRuntimeOptions,
    RuntimeMetadata,
    build_runtime_metadata,
    resolve_run_runtime,
)


pytestmark = pytest.mark.unit


def test_resolve_run_runtime_builds_per_stage_typed_handoff() -> None:
    options = RunOptions(
        executor="local",
        execution={"settings": {"run": "yes", "queue": "default"}},
        adapter_options={"local": {"mode": "safe"}},
        environment={
            "inherit": False,
            "set_variables": {"RUN_TOKEN": "secret"},
            "unset_variables": ["OLD_RUN"],
        },
        stage_options={
            "train": {
                "resources": {
                    "entries": {
                        "cpu": {"kind": "cpu", "amount": 2},
                    }
                },
                "execution": {"settings": {"queue": "short"}},
                "environment": {
                    "set_variables": {"STAGE_TOKEN": "secret"},
                    "unset_variables": ["OLD_STAGE"],
                },
                "adapter_options": {"slurm": {"partition": "debug"}},
            }
        },
    )

    resolved = resolve_run_runtime(options, stage_ids=("extract", "train"))

    train = resolved["train"]
    assert train.stage_id == "train"
    assert train.executor == "local"
    assert cast(ExecutionOptions, train.execution).settings == {
        "queue": "short",
        "run": "yes",
    }
    assert cast(ResourceRequest, train.resources).entries == {
        "cpu": ResourceEntry(kind="cpu", amount=2),
    }
    assert train.adapter_options.keys() == {"local", "slurm"}
    assert resolved["extract"].adapter_options.keys() == {"local"}


def test_runtime_metadata_is_safe_and_schema_versioned() -> None:
    metadata = build_runtime_metadata(
        RunOptions(
            run_uri="file:///runs/demo",
            executor="local",
            profile="cluster",
            tags={"team": "platform"},
            notes=("review",),
            environment={"set_variables": {"API_TOKEN": "secret"}},
            adapter_options={"slurm": {"account": "sensitive"}},
            stage_options={
                "train": {
                    "resources": {
                        "entries": {
                            "gpu": {
                                "kind": "gpu",
                                "amount": 1,
                            }
                        }
                    }
                }
            },
        ),
        stage_ids=("train",),
    )

    payload = metadata.to_dict()

    assert payload["schema_version"] == RUNTIME_METADATA_SCHEMA_VERSION
    assert payload["executor"] == "local"
    assert payload["profile"] == "cluster"
    assert payload["tags"] == {"team": "platform"}
    assert payload["environment"] == {
        "inherit": True,
        "set_variable_count": 1,
        "unset_variable_count": 0,
    }
    assert payload["adapter_options"] == {
        "namespace_count": 1,
        "namespaces": ["slurm"],
    }
    train = cast(dict[str, object], cast(dict[str, object], payload["stages"])["train"])
    resources = cast(dict[str, object], train["resources"])
    gpu = cast(dict[str, object], cast(dict[str, object], resources["entries"])["gpu"])
    assert gpu == {
        "kind": "gpu",
        "amount": 1,
        "unit": None,
        "attribute_count": 0,
    }
    assert "API_TOKEN" not in repr(payload)
    assert "sensitive" not in repr(payload)


def test_runtime_metadata_rejects_unknown_stage_options() -> None:
    with pytest.raises(RuntimeResourceError, match="unknown stage"):
        build_runtime_metadata(
            RunOptions(stage_options={"missing": {}}),
            stage_ids=("train",),
        )


def test_runtime_metadata_rejects_schema_version_mismatch() -> None:
    with pytest.raises(RuntimeResourceError, match="schema_version"):
        RuntimeMetadata(schema_version=999)


def test_resolve_run_runtime_reliability_defaults_to_run_level_conservative_policy() -> None:
    resolved = resolve_run_runtime(RunOptions(), stage_ids=("train",))

    assert isinstance(resolved["train"], ResolvedStageRuntimeOptions)
    assert resolved["train"].reliability == ReliabilityPolicy.defaults()


def test_resolve_run_runtime_merges_run_and_stage_reliability() -> None:
    options = RunOptions(
        reliability={
            "retry": {"enabled": True, "max_attempts": 4},
            "timeout": {"enabled": True, "duration_seconds": 120},
        },
        stage_options={
            "train": {
                "reliability": {"retry": {"enabled": False, "max_attempts": 1}},
            },
            "extract": {
                "reliability": {"timeout": {"enabled": False}},
            },
        },
    )
    resolved = resolve_run_runtime(options, stage_ids=("train", "extract"))

    assert cast(
        ReliabilityPolicy,
        resolved["train"].reliability,
    ) == ReliabilityPolicy(
        retry=RetryPolicy(enabled=False, max_attempts=1),
        timeout=TimeoutPolicy(enabled=True, duration_seconds=120),
    )
    assert cast(
        ReliabilityPolicy,
        resolved["extract"].reliability,
    ) == ReliabilityPolicy(
        retry=RetryPolicy(enabled=True, max_attempts=4),
        timeout=TimeoutPolicy(enabled=False),
    )
