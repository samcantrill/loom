"""Narrow integration coverage for runtime profile merge inputs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from loom.pipeline import RunStoreOptions, StageRuntimeOptions, merge_run_options
from loom.pipeline.execution import create_offline_evidence_run_store
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


def test_profile_selected_root_persists_a_run_in_that_collection(tmp_path: Path) -> None:
    root = str(tmp_path / "profile-runs")
    options = merge_run_options(
        base={"profile": "cluster"},
        profiles={"cluster": {"run_store": {"root": root}}},
    )
    assert isinstance(options.run_store, RunStoreOptions)
    assert options.run_store.root is not None

    store = create_offline_evidence_run_store(options.run_store.root)
    run_uri = store.allocate_run_uri()
    store.create_run(run_uri)

    assert root in run_uri
