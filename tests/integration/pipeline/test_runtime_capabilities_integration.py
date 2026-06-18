"""Integration coverage for runtime capability validation contracts."""

from __future__ import annotations

from typing import cast

import pytest

from loom.pipeline import (
    ExecutorDescriptor,
    ExecutorDescriptorRegistry,
    ResourceCapability,
    ResourceEntry,
    ResourceRequest,
    RunOptions,
    StageRuntimeOptions,
    merge_run_options,
    validate_executor_capabilities,
    validate_stage_runtime_options,
)
from loom.pipeline.resources import (
    DEFAULT_RESOURCE_VALIDATOR_REGISTRY,
    ResourceValidatorRegistry,
)


pytestmark = pytest.mark.integration


def test_merged_runtime_options_validate_against_default_local_descriptor() -> None:
    options = merge_run_options(
        base={
            "profile": "local",
            "stage_options": {
                "extract": {
                    "resources": {
                        "entries": {
                            "cpu": {"kind": "cpu", "amount": 1},
                        }
                    }
                }
            },
        },
        profiles={
            "local": {
                "executor": "local",
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
            "stage_options": {
                "train": {
                    "resources": {
                        "entries": {
                            "gpu": {
                                "kind": "gpu",
                                "amount": 0,
                            }
                        }
                    }
                }
            }
        },
        known_stage_ids={"extract", "train"},
    )

    validate_stage_runtime_options(options, known_stage_ids={"extract", "train"})
    result = validate_executor_capabilities(options)

    assert result.ok
    diagnostics = cast(list[dict[str, object]], result.to_dict()["diagnostics"])
    assert [(item["stage_id"], item["resource_kind"], item["code"]) for item in diagnostics] == [
        ("extract", "cpu", "resource.ignored"),
        ("train", "gpu", "resource.ignored"),
        ("train", "memory", "resource.ignored"),
    ]


def test_unknown_selected_executor_fails_capability_validation() -> None:
    options = RunOptions(executor="cluster")

    result = validate_executor_capabilities(options)

    assert not result.ok
    assert cast(list[dict[str, object]], result.to_dict()["diagnostics"])[0]["code"] == (
        "executor.unknown"
    )


def test_custom_descriptor_and_resource_registry_validate_registered_kinds() -> None:
    def _validate_scratch(entry: ResourceEntry, path: str) -> None:
        if entry.amount <= 0:
            raise AssertionError(f"{path}.amount should be positive")

    resource_registry = DEFAULT_RESOURCE_VALIDATOR_REGISTRY.compose(
        ResourceValidatorRegistry().with_validator("integration.scratch", _validate_scratch)
    )
    descriptor_registry = ExecutorDescriptorRegistry(
        {
            "batch": ExecutorDescriptor(
                name="batch",
                resource_capabilities={
                    "cpu": ResourceCapability(support_level="supported"),
                    "integration.scratch": ResourceCapability(support_level="advisory"),
                },
                adapter_namespaces=("batch",),
            )
        }
    )
    options = RunOptions(
        executor="batch",
        adapter_options={"slurm": {"partition": "debug"}, "batch": {"queue": "short"}},
        stage_options={
            "train": StageRuntimeOptions(
                resources=ResourceRequest(
                    entries={
                        "cpu": ResourceEntry(kind="cpu", amount=2),
                        "integration.scratch": ResourceEntry(
                            kind="integration.scratch",
                            amount=20,
                            unit="GiB",
                        ),
                    },
                    validator_registry=resource_registry,
                ),
                adapter_options={"batch": {"stage_queue": "gpu"}},
            )
        },
    )

    result = validate_executor_capabilities(options, registry=descriptor_registry)

    assert result.ok
    diagnostics = cast(list[dict[str, object]], result.to_dict()["diagnostics"])
    assert [(item["code"], item["resource_kind"], item["adapter_namespace"]) for item in diagnostics] == [
        ("adapter_namespace.unclaimed", None, "slurm"),
        ("resource.supported", "cpu", None),
        ("resource.advisory", "integration.scratch", None),
    ]
