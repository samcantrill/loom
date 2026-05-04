"""Unit tests for runtime and resource foundation models."""

from typing import Any, cast

import pytest

from loom.pipeline import (
    ResourceRequest,
    RuntimeKind,
    RuntimeRequest,
    parse_resource_request,
    parse_runtime_request,
)
from loom.pipeline.errors import RuntimeResourceError


def test_resource_request_round_trips_and_freezes_custom() -> None:
    custom: dict[str, Any] = {"labels": ["fast"]}
    request = ResourceRequest(cpus=2, memory_mb=1024, gpus=0, custom=custom)
    custom["labels"].append("mutated")

    assert request.custom == {"labels": ("fast",)}
    assert request.to_dict() == {
        "schema_version": 1,
        "cpus": 2,
        "memory_mb": 1024,
        "gpus": 0,
        "custom": {"labels": ["fast"]},
    }
    assert ResourceRequest.from_dict(request.to_dict()) == request
    with pytest.raises(TypeError):
        cast(Any, request.custom)["labels"] = ["changed"]


def test_parse_resource_request_accepts_authored_subset_without_schema() -> None:
    request = parse_resource_request(
        {"cpus": 1, "memory_mb": 512, "gpus": 0, "custom": {"queue": "local"}}
    )

    assert request.cpus == 1
    assert request.memory_mb == 512
    assert request.gpus == 0
    assert request.custom == {"queue": "local"}


@pytest.mark.parametrize(
    "resources",
    [
        {"cpus": 0},
        {"cpus": True},
        {"memory_mb": -1},
        {"gpus": -1},
        {"custom": []},
        {"unknown": 1},
        {"timeout_seconds": 30},
        {"custom": {"slurm": {"partition": "gpu"}}},
    ],
)
def test_resource_request_rejects_invalid_or_deferred_fields(
    resources: dict[str, object],
) -> None:
    with pytest.raises(RuntimeResourceError):
        parse_resource_request(resources)


def test_runtime_request_round_trips_local_runtime() -> None:
    request = RuntimeRequest(
        kind=RuntimeKind.LOCAL,
        resources=ResourceRequest(cpus=1),
        metadata={"note": "local"},
    )

    assert request.to_dict() == {
        "schema_version": 1,
        "kind": "LOCAL",
        "resources": {
            "schema_version": 1,
            "cpus": 1,
            "memory_mb": None,
            "gpus": None,
            "custom": {},
        },
        "metadata": {"note": "local"},
    }
    assert RuntimeRequest.from_dict(request.to_dict()) == request
    assert parse_runtime_request(request.to_dict()) == request


@pytest.mark.parametrize(
    "runtime",
    [
        {"schema_version": 1, "kind": "SLURM", "resources": {}, "metadata": {}},
        {"schema_version": 1, "kind": "LOCAL", "resources": {}, "metadata": {}, "executor": "local"},
        {"schema_version": 1, "kind": "LOCAL", "resources": {}, "metadata": {}, "timeout": 5},
        {"schema_version": 1, "kind": "LOCAL", "resources": {}, "metadata": {}, "container": {}},
    ],
)
def test_runtime_request_rejects_unsupported_runtime_fields(
    runtime: dict[str, object],
) -> None:
    with pytest.raises(RuntimeResourceError):
        RuntimeRequest.from_dict(runtime)
