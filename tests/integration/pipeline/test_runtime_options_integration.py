"""Narrow integration coverage for Python runtime option construction."""

from __future__ import annotations

import pytest

from loom.pipeline import (
    ResourceEntry,
    ResourceRequest,
    RunOptions,
    StageRuntimeOptions,
    validate_stage_runtime_options,
)
from loom.pipeline.errors import RuntimeResourceError


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
                        "gpu": {"kind": "gpu", "amount": 0},
                    }
                }
            },
        },
    )

    validate_stage_runtime_options(options, known_stage_ids={"extract", "train"})
    assert RunOptions.from_dict(options.to_dict()) == options
    with pytest.raises(RuntimeResourceError, match="unknown stage id"):
        validate_stage_runtime_options(options, known_stage_ids={"extract"})
