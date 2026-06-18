"""Narrow integration coverage for runtime profile merge inputs."""

from __future__ import annotations

from typing import cast
from collections.abc import Mapping

import pytest

from loom.pipeline import StageRuntimeOptions, merge_run_options
from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.reliability import ReliabilityPolicy, RetryPolicy, TimeoutPolicy


pytestmark = pytest.mark.integration


def test_config_shaped_runtime_profile_dicts_merge_with_known_stage_ids() -> None:
    result = merge_run_options(
        base={
            "profile": "cluster",
            "executor": "local",
            "tags": {"suite": "integration"},
            "stage_options": {
                "extract": {
                    "resources": {
                        "entries": {"cpu": {"kind": "cpu", "amount": 1}}
                    }
                }
            },
        },
        profiles={
            "cluster": {
                "executor": "slurm",
                "slurm": {"partition": "debug"},
                "stage_options": {
                    "train": {
                        "resources": {
                            "entries": {
                                "memory": {
                                    "kind": "memory",
                                    "amount": 2,
                                    "unit": "GiB",
                                }
                            }
                        }
                    }
                },
            }
        },
        explicit={
            "tags": {"invocation": "api"},
            "stage_options": {
                "train": {
                    "resources": {
                        "entries": {"cpu": {"kind": "cpu", "amount": 4}}
                    }
                }
            },
        },
        known_stage_ids={"extract", "train"},
    )

    assert result.executor == "slurm"
    assert result.profile == "cluster"
    assert result.tags == {"invocation": "api", "suite": "integration"}
    assert result.adapter_options == {"slurm": {"partition": "debug"}}
    assert set(result.stage_options) == {"extract", "train"}


def test_profile_null_clearing_skips_profile_and_known_stage_validation_is_deterministic() -> None:
    result = merge_run_options(
        base={
            "profile": "cluster",
            "executor": "local",
            "stage_options": {"extract": {}},
        },
        profiles={
            "cluster": {
                "executor": "slurm",
                "stage_options": {"unknown_profile_stage": {}},
            }
        },
        explicit={"profile": None},
        known_stage_ids={"extract"},
    )

    assert result.profile is None
    assert result.executor == "local"
    assert set(result.stage_options) == {"extract"}

    with pytest.raises(RuntimeResourceError, match="unknown stage id"):
        merge_run_options(
            base={"profile": "cluster"},
            profiles={
                "cluster": {
                    "stage_options": {"unknown_profile_stage": {}},
                }
            },
            known_stage_ids={"extract"},
        )


def test_profile_merge_preserves_run_and_stage_reliability_contracts() -> None:
    result = merge_run_options(
        base={"reliability": {"retry": {"enabled": True, "max_attempts": 5}}},
        profiles={
            "cluster": {
                "reliability": {"timeout": {"enabled": False}},
                "stage_options": {
                    "train": {
                        "reliability": {"retry": {"enabled": True, "max_attempts": 2}}
                    }
                },
            }
        },
        explicit={
            "profile": "cluster",
            "stage_options": {
                "train": {
                    "reliability": {
                        "timeout": {"enabled": True, "duration_seconds": 12}
                    }
                }
            },
        },
    )

    assert result.reliability == ReliabilityPolicy(
        retry=RetryPolicy(enabled=True, max_attempts=5),
        timeout=TimeoutPolicy(enabled=False),
    )
    stage_options = cast(Mapping[str, StageRuntimeOptions], result.stage_options)
    assert stage_options["train"].reliability == ReliabilityPolicy(
        retry=RetryPolicy(enabled=True, max_attempts=2),
        timeout=TimeoutPolicy(enabled=True, duration_seconds=12),
    )
