"""Unit tests for runtime profiles and merge semantics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from loom.pipeline import (
    ExecutionOptions,
    ResourceEntry,
    ResourceRequest,
    RunEnvironmentRequest,
    RunOptions,
    RuntimeProfile,
    RuntimeProfileCollection,
    StageEnvironmentRequest,
    StageRuntimeOptions,
    ResolvedStageRuntimeOptions,
    resolve_run_runtime,
    merge_run_options,
    parse_runtime_profile,
    parse_runtime_profiles,
    select_runtime_profile,
)
from loom.pipeline.reliability import ReliabilityPolicy, RetryPolicy, TimeoutPolicy
from loom.pipeline.errors import RuntimeResourceError


def test_runtime_profile_serializes_sparse_core_fields_and_adapter_sections() -> None:
    profile = RuntimeProfile.from_dict(
        {
            "executor": "slurm",
            "dry_run": True,
            "tags": {"team": "science"},
            "execution": {"settings": {"max_parallel_stages": 2}},
            "environment": {
                "inherit": False,
                "set_variables": {"TOKEN": "secret"},
            },
            "stage_options": {
                "train": {
                    "resources": {
                        "entries": {
                            "cpu": {"kind": "cpu", "amount": 2},
                        }
                    },
                    "adapter_options": {"docker": {"image": "runtime:latest"}},
                }
            },
            "adapter_options": {"local": {"log_level": "debug"}},
            "slurm": {"partition": "debug"},
        }
    )

    assert profile.to_dict() == {
        "adapter_options": {
            "local": {"log_level": "debug"},
            "slurm": {"partition": "debug"},
        },
        "dry_run": True,
        "environment": {
            "inherit": False,
            "set_variables": {"TOKEN": "secret"},
        },
        "execution": {"settings": {"max_parallel_stages": 2}},
        "executor": "slurm",
        "stage_options": {
            "train": {
                "adapter_options": {"docker": {"image": "runtime:latest"}},
                "resources": {
                    "entries": {
                        "cpu": {
                            "amount": 2,
                            "attributes": {},
                            "kind": "cpu",
                            "unit": None,
                        }
                    }
                },
            }
        },
        "tags": {"team": "science"},
    }
    with pytest.raises(TypeError):
        cast(Any, profile.options)["executor"] = "local"
    with pytest.raises(TypeError):
        cast(Any, profile.options["adapter_options"])["local"] = {}


@pytest.mark.parametrize(
    "data",
    [
        {"schema_version": 1},
        {"profile": "nested"},
        {"execution": {"unknown": True}},
        {"stage_options": {"bad.stage": {}}},
        {"adapter_options": {"slurm": object()}},
        {"adapter_options": {"slurm": {}}, "slurm": {}},
    ],
)
def test_runtime_profile_rejects_reserved_and_invalid_fields(data: object) -> None:
    with pytest.raises(RuntimeResourceError):
        RuntimeProfile.from_dict(data)


def test_runtime_profile_collection_selects_profiles_deterministically() -> None:
    profiles = RuntimeProfileCollection.from_dict(
        {
            "debug": {"executor": "local"},
            "cluster": {"executor": "slurm"},
        }
    )

    assert list(profiles.profiles) == ["cluster", "debug"]
    assert profiles.select(None) is None
    assert profiles.select("debug") == RuntimeProfile({"executor": "local"})
    assert parse_runtime_profile({"executor": "local"}) == profiles.select("debug")
    assert parse_runtime_profiles(profiles.to_dict()) == profiles
    assert select_runtime_profile(profiles, "cluster") == profiles.select("cluster")
    with pytest.raises(RuntimeResourceError, match="not defined"):
        profiles.select("missing")
    with pytest.raises(RuntimeResourceError):
        RuntimeProfileCollection.from_dict({"": {"executor": "local"}})


def test_runtime_profile_container_shorthand_preserves_namespace_contract() -> None:
    profile = RuntimeProfile.from_dict(
        {
            "executor": "docker",
            "container": {
                "image": {"reference": "python:3.12"},
                "workdir": "/workspace",
                "mounts": [
                    {
                        "source": "/workspace",
                        "target": "/workspace",
                        "mode": "rw",
                    }
                ],
                "environment": {
                    "variables": {"TOKEN": "secret"},
                    "required_host_variables": ["HOME"],
                },
            },
            "docker": {"pull": "never"},
        }
    )

    assert profile.to_dict() == {
        "adapter_options": {
            "container": {
                "image": {"reference": "python:3.12"},
                "workdir": "/workspace",
                "mounts": [
                    {
                        "source": "/workspace",
                        "target": "/workspace",
                        "mode": "rw",
                    }
                ],
                "environment": {
                    "variables": {"TOKEN": "secret"},
                    "required_host_variables": ["HOME"],
                },
            },
            "docker": {"pull": "never"},
        },
        "executor": "docker",
    }


def test_merge_run_options_applies_base_profile_explicit_precedence() -> None:
    base = {
        "executor": "local",
        "dry_run": True,
        "profile": "cluster",
        "tags": {"keep": "base", "team": "base"},
        "notes": ["base note"],
        "selectors": {"from_stage": "extract", "only_stages": ["extract"]},
        "resume": {"enabled": False},
        "execution": {"settings": {"keep": "base", "queue": "base"}},
        "environment": {
            "inherit": False,
            "set_variables": {"BASE": "1"},
            "unset_variables": ["BASE_OLD"],
        },
        "adapter_options": {"slurm": {"partition": "base", "account": "base"}},
        "stage_options": {
            "train": {
                "resources": {
                    "entries": {
                        "cpu": {"kind": "cpu", "amount": 1},
                    }
                },
                "execution": {"settings": {"queue": "base", "stage_keep": "base"}},
                "environment": {
                    "set_variables": {"STAGE_BASE": "1"},
                    "unset_variables": ["STAGE_OLD"],
                },
                "adapter_options": {"docker": {"image": "base"}},
            }
        },
    }
    profiles = {
        "cluster": {
            "executor": "slurm",
            "tags": {"team": "profile"},
            "notes": ["profile note"],
            "selectors": {"skip_stages": ["publish"]},
            "resume": {"enabled": True},
            "execution": {"settings": {"queue": "profile"}},
            "environment": {
                "set_variables": {"PROFILE": "1"},
                "unset_variables": [],
            },
            "adapter_options": {"slurm": {"partition": "profile"}},
            "docker": {"image": "profile-top"},
            "stage_options": {
                "train": {
                    "resources": {
                        "entries": {
                            "memory": {
                                "kind": "memory",
                                "amount": 4,
                                "unit": "GiB",
                            }
                        }
                    },
                    "execution": {"settings": {"queue": "profile"}},
                    "environment": {
                        "set_variables": {"STAGE_PROFILE": "1"},
                        "unset_variables": [],
                    },
                    "adapter_options": {"docker": {"image": "profile"}},
                },
                "evaluate": {
                    "resources": {
                        "entries": {"gpu": {"kind": "gpu", "amount": 0}}
                    }
                },
            },
        }
    }
    explicit = {
        "dry_run": False,
        "tags": {"owner": "explicit"},
        "notes": [],
        "selectors": {"from_stage": None, "only_stages": ["train"]},
        "execution": {"settings": {"priority": "high"}},
        "environment": {
            "inherit": True,
            "set_variables": {"EXPLICIT": "1"},
        },
        "adapter_options": {"slurm": {"partition": "explicit"}},
        "stage_options": {
            "train": {
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 4}}
                },
                "execution": {"settings": {"priority": "high"}},
                "environment": {"unset_variables": ["STAGE_EXPLICIT_OLD"]},
                "adapter_options": {"docker": {"image": "explicit"}},
            }
        },
    }

    result = merge_run_options(
        base=base,
        profiles=profiles,
        explicit=explicit,
        known_stage_ids={"train", "evaluate"},
    )

    assert result.executor == "slurm"
    assert result.dry_run is False
    assert result.profile == "cluster"
    assert result.tags == {
        "keep": "base",
        "owner": "explicit",
        "team": "profile",
    }
    assert result.notes == ()
    assert result.to_plan_selectors().from_stage is None
    assert result.to_plan_selectors().only_stages == ("train",)
    assert result.to_plan_selectors().skip_stages == ("publish",)
    assert result.to_resume_options().enabled is True
    execution = cast(ExecutionOptions, result.execution)
    environment = cast(RunEnvironmentRequest, result.environment)
    stage_options = cast(Mapping[str, StageRuntimeOptions], result.stage_options)

    assert execution.settings == {
        "keep": "base",
        "priority": "high",
        "queue": "profile",
    }
    assert environment.inherit is True
    assert environment.set_variables == {
        "BASE": "1",
        "EXPLICIT": "1",
        "PROFILE": "1",
    }
    assert environment.unset_variables == ()
    assert result.adapter_options == {
        "docker": {"image": "profile-top"},
        "slurm": {"partition": "explicit"},
    }

    train = stage_options["train"]
    assert cast(ResourceRequest, train.resources).entries == {
        "cpu": ResourceEntry(kind="cpu", amount=4),
        "memory": ResourceEntry(kind="memory", amount=4, unit="GiB"),
    }
    train_execution = cast(ExecutionOptions, train.execution)
    train_environment = cast(StageEnvironmentRequest, train.environment)
    assert train_execution.settings == {
        "priority": "high",
        "queue": "profile",
        "stage_keep": "base",
    }
    assert train_environment.set_variables == {
        "STAGE_BASE": "1",
        "STAGE_PROFILE": "1",
    }
    assert train_environment.unset_variables == ("STAGE_EXPLICIT_OLD",)
    assert train.adapter_options == {"docker": {"image": "explicit"}}
    assert "evaluate" in stage_options


def test_sparse_empty_mappings_do_not_delete_lower_mapping_values() -> None:
    result = merge_run_options(
        base={
            "tags": {"team": "base"},
            "execution": {"settings": {"queue": "base"}},
            "adapter_options": {"slurm": {"partition": "base"}},
            "stage_options": {
                "train": {
                    "resources": {
                        "entries": {"cpu": {"kind": "cpu", "amount": 2}}
                    },
                    "execution": {"settings": {"queue": "base"}},
                    "adapter_options": {"docker": {"image": "base"}},
                }
            },
        },
        explicit={
            "tags": {},
            "execution": {"settings": {}},
            "adapter_options": {},
            "stage_options": {
                "train": {
                    "resources": {"entries": {}},
                    "execution": {"settings": {}},
                    "adapter_options": {},
                }
            },
        },
    )

    assert result.tags == {"team": "base"}
    execution = cast(ExecutionOptions, result.execution)
    stage_options = cast(Mapping[str, StageRuntimeOptions], result.stage_options)

    assert execution.settings == {"queue": "base"}
    assert result.adapter_options == {"slurm": {"partition": "base"}}
    train = stage_options["train"]
    assert cast(ResourceRequest, train.resources).entries == {
        "cpu": ResourceEntry(kind="cpu", amount=2)
    }
    train_execution = cast(ExecutionOptions, train.execution)
    assert train_execution.settings == {"queue": "base"}
    assert train.adapter_options == {"docker": {"image": "base"}}


def test_typed_run_options_source_is_fully_supplied_but_mapping_fields_overlay() -> None:
    explicit = RunOptions()
    result = merge_run_options(
        base={
            "executor": "slurm",
            "dry_run": True,
            "profile": "cluster",
            "tags": {"team": "base"},
            "notes": ["base"],
            "selectors": {"only_stages": ["extract"], "skip_stages": ["publish"]},
            "environment": {
                "inherit": False,
                "set_variables": {"BASE": "1"},
                "unset_variables": ["BASE_OLD"],
            },
        },
        profiles={"cluster": {"executor": "local"}},
        explicit=explicit,
    )

    assert result.executor is None
    assert result.dry_run is False
    assert result.profile is None
    assert result.tags == {"team": "base"}
    assert result.notes == ()
    assert result.to_plan_selectors().only_stages == ()
    assert result.to_plan_selectors().skip_stages == ()
    environment = cast(RunEnvironmentRequest, result.environment)
    assert environment.inherit is True
    assert environment.set_variables == {"BASE": "1"}
    assert environment.unset_variables == ()


def test_profile_selection_failures_and_null_clearing_are_explicit() -> None:
    assert (
        merge_run_options(
            base={"profile": "cluster", "executor": "local"},
            profiles={"cluster": {"executor": "slurm"}},
            explicit={"profile": None},
        ).executor
        == "local"
    )
    direct = merge_run_options(
        profiles={"cluster": {"executor": "slurm"}},
        profile="cluster",
    )
    assert direct.profile == "cluster"
    assert direct.executor == "slurm"
    with pytest.raises(RuntimeResourceError, match="not defined"):
        merge_run_options(base={"profile": "missing"}, profiles={"cluster": {}})
    with pytest.raises(RuntimeResourceError, match="no runtime profiles"):
        merge_run_options(base={"profile": "cluster"})


def test_known_stage_validation_is_applied_after_merge() -> None:
    result = merge_run_options(
        base={"stage_options": {"extract": StageRuntimeOptions()}},
        explicit={"stage_options": {"train": {}}},
        known_stage_ids={"extract", "train"},
    )

    assert set(result.stage_options) == {"extract", "train"}
    with pytest.raises(RuntimeResourceError, match="unknown stage id"):
        merge_run_options(
            base={"stage_options": {"extract": {}}},
            profiles={"cluster": {"stage_options": {"train": {}}}},
            explicit={"profile": "cluster"},
            known_stage_ids={"extract"},
        )


def test_merge_run_options_respects_run_level_reliability_precedence() -> None:
    result = merge_run_options(
        base={"reliability": {"retry": {"enabled": True, "max_attempts": 3}}},
        profiles={"cluster": {"reliability": {"timeout": {"enabled": True, "duration_seconds": 30}}}},
        explicit={"reliability": {"retry": {"enabled": False, "max_attempts": 1}}},
        profile="cluster",
        known_stage_ids={"train"},
    )

    assert result.reliability == ReliabilityPolicy(
        retry=RetryPolicy(enabled=False, max_attempts=1),
        timeout=TimeoutPolicy(enabled=True, duration_seconds=30),
    )


def test_merge_run_options_merges_stage_reliability_with_run_level_defaults() -> None:
    result = merge_run_options(
        base={"stage_options": {"train": {"reliability": {"retry": {"enabled": True, "max_attempts": 2}}}}},
        explicit={"reliability": {"timeout": {"enabled": False}}},
        known_stage_ids={"train"},
    )
    resolved = resolve_run_runtime(result, stage_ids=("train",))

    assert cast(ResolvedStageRuntimeOptions, resolved["train"]).reliability == ReliabilityPolicy(
        retry=RetryPolicy(enabled=True, max_attempts=2),
        timeout=TimeoutPolicy(enabled=False),
    )
