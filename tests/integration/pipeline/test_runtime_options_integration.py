"""Narrow integration coverage for Python runtime option construction."""

from __future__ import annotations

from typing import cast

import pytest

from loom.pipeline import (
    ResourceEntry,
    ResourceRequest,
    RunOptions,
    StageRuntimeOptions,
    validate_stage_runtime_options,
)
from loom.pipeline.reliability import ReliabilityPolicy, RetryPolicy, TimeoutPolicy
from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.runtime import resolve_run_runtime


def test_python_callers_construct_runtime_options_for_exact_stage_ids() -> None:
    options = RunOptions(
        run_uri="runs/python-api",
        executor="local",
        stage_options={
            "extract": StageRuntimeOptions(
                resources=ResourceRequest(
                    entries={
                        "cpu": ResourceEntry(kind="cpu", amount=1),
                        "memory": ResourceEntry(kind="memory", amount=256, unit="MiB"),
                    }
                )
            ),
            "train": {
                "resources": {
                    "entries": {
                        "gpu": {"kind": "gpu", "amount": 1},
                    }
                }
            },
        },
    )

    validate_stage_runtime_options(options, known_stage_ids={"extract", "train"})
    assert RunOptions.from_dict(options.to_dict()) == options
    with pytest.raises(RuntimeResourceError, match="unknown stage id"):
        validate_stage_runtime_options(options, known_stage_ids={"extract"})


def test_runtime_options_reliability_parses_and_merges_in_python_api() -> None:
    options = RunOptions(
        reliability={"retry": {"enabled": True, "max_attempts": 3}},
        stage_options={
            "extract": {
                "reliability": {
                    "timeout": {"enabled": False},
                }
            },
            "train": {},
        },
    )

    validate_stage_runtime_options(options, known_stage_ids={"extract", "train"})
    resolved = resolve_run_runtime(options, stage_ids=("extract", "train"))
    assert options.reliability == ReliabilityPolicy(
        retry=RetryPolicy(enabled=True, max_attempts=3),
        timeout=None,
    )
    assert cast(
        ReliabilityPolicy,
        resolved["extract"].reliability,
    ) == ReliabilityPolicy(
        retry=RetryPolicy(enabled=True, max_attempts=3),
        timeout=TimeoutPolicy(enabled=False),
    )
