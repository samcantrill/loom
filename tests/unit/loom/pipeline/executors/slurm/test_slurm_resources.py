"""Unit tests for SLURM resource mapping."""

from __future__ import annotations

import pytest

from loom.pipeline.executors.slurm import (
    SlurmOptions,
    SlurmResourceMappingError,
    build_sbatch_directives,
    map_slurm_resources,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest


def test_maps_cpu_memory_and_gpu_resources_to_sbatch_directives() -> None:
    resources = ResourceRequest(
        entries={
            "cpu": ResourceEntry(kind="cpu", amount=8, unit="count"),
            "memory": ResourceEntry(kind="memory", amount=32, unit="GiB"),
            "gpu": ResourceEntry(kind="gpu", amount=2, unit="count"),
        }
    )

    directives = map_slurm_resources(resources)

    assert [directive.to_dict() for directive in directives] == [
        {"name": "cpus-per-task", "value": "8", "source": "resource:cpu"},
        {"name": "gres", "value": "gpu:2", "source": "resource:gpu"},
        {"name": "mem", "value": "32G", "source": "resource:memory"},
    ]


def test_missing_gpu_produces_no_gres_directive() -> None:
    resources = ResourceRequest(entries={})

    assert map_slurm_resources(resources) == ()


@pytest.mark.parametrize(
    "resource, options, message",
    [
        (
            ResourceEntry(kind="cpu", amount=2, unit="count"),
            SlurmOptions(cpus_per_task=2),
            "resources.entries\\['cpu'\\].*cpus_per_task",
        ),
        (
            ResourceEntry(kind="memory", amount=4, unit="GiB"),
            SlurmOptions(mem="4G"),
            "resources.entries\\['memory'\\].*mem",
        ),
        (
            ResourceEntry(kind="gpu", amount=1, unit="count"),
            SlurmOptions(gres="gpu:1"),
            "resources.entries\\['gpu'\\].*gres",
        ),
    ],
)
def test_resource_option_conflicts_are_path_aware(
    resource: ResourceEntry,
    options: SlurmOptions,
    message: str,
) -> None:
    resources = {resource.kind: resource}

    with pytest.raises(SlurmResourceMappingError, match=message):
        map_slurm_resources(resources, options=options)


def test_memory_mapping_rejects_unsupported_units() -> None:
    resources = ResourceRequest(
        entries={"memory": ResourceEntry(kind="memory", amount=1024, unit="KiB")}
    )

    with pytest.raises(
        SlurmResourceMappingError, match=r"resources.entries\['memory'\].unit"
    ):
        map_slurm_resources(resources)


def test_memory_mapping_rejects_non_integer_amounts() -> None:
    resources = ResourceRequest(
        entries={"memory": ResourceEntry(kind="memory", amount=1.5, unit="GiB")}
    )

    with pytest.raises(
        SlurmResourceMappingError, match=r"resources.entries\['memory'\].amount"
    ):
        map_slurm_resources(resources)


def test_direct_mapping_rejects_resource_attributes() -> None:
    resources = {
        "gpu": ResourceEntry(
            kind="gpu",
            amount=1,
            unit="count",
            attributes={"model": "a100"},
        )
    }

    with pytest.raises(
        SlurmResourceMappingError, match=r"resources.entries\['gpu'\].attributes"
    ):
        map_slurm_resources(resources)


def test_build_sbatch_directives_combines_options_resources_and_extra() -> None:
    resources = ResourceRequest(
        entries={"cpu": ResourceEntry(kind="cpu", amount=4, unit="count")}
    )
    options = SlurmOptions(partition="debug", extra_sbatch={"requeue": True})

    directives = build_sbatch_directives(options=options, resources=resources)

    assert [directive.to_dict() for directive in directives] == [
        {"name": "partition", "value": "debug", "source": "option"},
        {"name": "cpus-per-task", "value": "4", "source": "resource:cpu"},
        {"name": "requeue", "value": True, "source": "extra_sbatch"},
    ]
