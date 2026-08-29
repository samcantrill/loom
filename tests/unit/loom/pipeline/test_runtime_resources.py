"""Unit tests for runtime and resource foundation models."""

from typing import Any, cast

import pytest

from loom.pipeline import (
    ResourceEntry,
    ResourceRequest,
    RuntimeKind,
    RuntimeRequest,
    parse_resource_request,
    parse_runtime_request,
)
from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import (
    DEFAULT_RESOURCE_VALIDATOR_REGISTRY,
    RESOURCE_SCHEMA_VERSION,
    ResourceValidatorRegistry,
    validate_resource_kind,
)
from loom.pipeline.runtime import StageRuntimeOptions, merge_config_run_options
from loom.pipeline.validation import validate_pipeline_config


def test_runtime_public_import_paths_are_compatible() -> None:
    import loom.pipeline.runtime as runtime
    from loom.pipeline import RuntimeKind as PipelineRuntimeKind
    from loom.pipeline import RuntimeRequest as PipelineRuntimeRequest
    from loom.pipeline import parse_runtime_request as pipeline_parse_runtime_request
    from loom.pipeline.runtime import RuntimeKind as RuntimeModuleKind
    from loom.pipeline.runtime import RuntimeRequest as RuntimeModuleRequest
    from loom.pipeline.runtime import parse_runtime_request as runtime_module_parse

    assert runtime.RuntimeKind is RuntimeModuleKind is PipelineRuntimeKind
    assert runtime.RuntimeRequest is RuntimeModuleRequest is PipelineRuntimeRequest
    assert runtime.parse_runtime_request is runtime_module_parse
    assert runtime_module_parse is pipeline_parse_runtime_request
    assert runtime_module_parse(None) == RuntimeModuleRequest()


def test_resource_entry_request_round_trip_and_freeze_attributes() -> None:
    registry = ResourceValidatorRegistry().with_validator(
        "slurm.gres", lambda entry, path: None
    )
    attributes: dict[str, Any] = {"labels": ["fast"]}
    entry = ResourceEntry(kind="slurm.gres", amount=1, unit=None, attributes=attributes)
    attributes["labels"].append("mutated")
    request = ResourceRequest(
        entries={"slurm.gres": entry}, validator_registry=registry
    )

    assert entry.attributes == {"labels": ("fast",)}
    assert request.to_dict() == {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "entries": {
            "slurm.gres": {
                "kind": "slurm.gres",
                "amount": 1,
                "unit": None,
                "attributes": {"labels": ["fast"]},
            },
        },
    }
    assert ResourceRequest.from_dict(request.to_dict(), registry=registry) == request
    with pytest.raises(TypeError):
        cast(Any, entry.attributes)["labels"] = ["changed"]


def test_parse_resource_request_accepts_authored_entries_without_schema() -> None:
    request = parse_resource_request(
        {
            "entries": {
                "cpu": {"kind": "cpu", "amount": 2, "unit": "count"},
                "memory": {"kind": "memory", "amount": 512, "unit": "MiB"},
                "gpu": {"kind": "gpu", "amount": 1},
            },
        }
    )

    assert request.entries["cpu"] == ResourceEntry(kind="cpu", amount=2, unit="count")
    assert request.entries["memory"] == ResourceEntry(
        kind="memory", amount=512, unit="MiB"
    )
    assert request.entries["gpu"] == ResourceEntry(kind="gpu", amount=1)


@pytest.mark.parametrize(
    "kind",
    [
        "cpu",
        "slurm.gres",
        "adapter_1.memory_pool",
        "a.b_c.d2",
    ],
)
def test_resource_kind_syntax_accepts_lowercase_ascii_segments(kind: str) -> None:
    assert validate_resource_kind(kind) == kind


@pytest.mark.parametrize(
    "kind",
    [
        "",
        "CPU",
        "gpu-count",
        "slurm/gres",
        ".cpu",
        "cpu.",
        "cpu..memory",
        "cpu memory",
        "mémoire",
        "1cpu",
        "cpu.Memory",
    ],
)
def test_resource_kind_syntax_rejects_invalid_kinds(kind: str) -> None:
    with pytest.raises(RuntimeResourceError):
        validate_resource_kind(kind)


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"kind": "cpu", "amount": 0}, "positive integer"),
        ({"kind": "cpu", "amount": 1.5}, "positive integer"),
        ({"kind": "cpu", "amount": True}, "finite numeric"),
        ({"kind": "cpu", "amount": 1, "unit": "cores"}, "count"),
        ({"kind": "cpu", "amount": 1, "attributes": {"hint": "x"}}, "attributes"),
        ({"kind": "memory", "amount": 0, "unit": "MiB"}, "positive"),
        ({"kind": "memory", "amount": float("inf"), "unit": "MiB"}, "plain-data"),
        ({"kind": "memory", "amount": 1, "unit": "MB"}, "one of"),
        ({"kind": "memory", "amount": 1}, "one of"),
        ({"kind": "memory", "amount": True, "unit": "MiB"}, "finite numeric"),
        (
            {"kind": "memory", "amount": 1, "unit": "MiB", "attributes": {"node": "a"}},
            "attributes",
        ),
        ({"kind": "gpu", "amount": -1}, "positive integer"),
        ({"kind": "gpu", "amount": 0}, "positive integer"),
        ({"kind": "gpu", "amount": 0.5}, "positive integer"),
        ({"kind": "gpu", "amount": True}, "finite numeric"),
        ({"kind": "gpu", "amount": 1, "unit": "device"}, "count"),
        ({"kind": "gpu", "amount": 1, "attributes": {"model": "a100"}}, "attributes"),
    ],
)
def test_builtin_resource_validators_reject_invalid_amounts_units_and_attributes(
    entry: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(RuntimeResourceError, match=message):
        parse_resource_request({"entries": {cast(str, entry["kind"]): entry}})


@pytest.mark.parametrize("amount", [1, 1.5])
def test_memory_accepts_positive_integer_or_finite_numeric_amount(
    amount: int | float,
) -> None:
    request = parse_resource_request(
        {"entries": {"memory": {"kind": "memory", "amount": amount, "unit": "GiB"}}}
    )

    assert request.entries["memory"].amount == amount


def test_resource_request_keys_must_match_entry_kinds() -> None:
    with pytest.raises(RuntimeResourceError, match="match its mapping key"):
        ResourceRequest(
            entries={"cpu": ResourceEntry(kind="memory", amount=1, unit="MiB")}
        )


@pytest.mark.parametrize(
    "resources",
    [
        {"cpus": 1},
        {"memory_mb": 512},
        {"gpus": 0},
        {"custom": {"queue": "local"}},
        {"schema_version": RESOURCE_SCHEMA_VERSION, "entries": {}},
        {"cpu": {"kind": "cpu", "amount": 1}},
    ],
)
def test_authored_resources_reject_old_schema_and_noncanonical_shapes(
    resources: dict[str, object],
) -> None:
    with pytest.raises(RuntimeResourceError):
        parse_resource_request(resources)


@pytest.mark.parametrize("field", ["cpus", "memory_mb", "gpus", "custom"])
def test_resource_request_constructor_rejects_old_fields(field: str) -> None:
    with pytest.raises(TypeError):
        ResourceRequest(**{field: 1})  # type: ignore[arg-type]


def test_resource_request_from_dict_rejects_old_serialized_fields() -> None:
    old_document = {
        "schema_version": 1,
        "cpus": 1,
        "memory_mb": 512,
        "gpus": 0,
        "custom": {},
    }

    with pytest.raises(RuntimeResourceError):
        ResourceRequest.from_dict(old_document)

    with pytest.raises(RuntimeResourceError, match="unknown field"):
        ResourceRequest.from_dict(
            {
                "schema_version": RESOURCE_SCHEMA_VERSION,
                "entries": {},
                "cpus": 1,
            }
        )
    with pytest.raises(RuntimeResourceError, match="unknown field"):
        ResourceRequest.from_dict(
            {
                "schema_version": RESOURCE_SCHEMA_VERSION,
                "entries": {},
                "timeout": 30,
            }
        )


def test_registry_registration_and_composition_are_explicit_and_isolated() -> None:
    def _validate_local_scratch(entry: ResourceEntry, path: str) -> None:
        if entry.amount <= 0:
            raise RuntimeResourceError(f"{path}.amount must be positive")

    custom = ResourceValidatorRegistry().with_validator(
        "local.scratch",
        _validate_local_scratch,
    )
    composed = DEFAULT_RESOURCE_VALIDATOR_REGISTRY.compose(custom)
    authored = {
        "entries": {
            "local.scratch": {
                "kind": "local.scratch",
                "amount": 10,
                "unit": "GiB",
                "attributes": {"mount": "/tmp"},
            },
        },
    }

    with pytest.raises(RuntimeResourceError, match="unregistered"):
        parse_resource_request(authored)
    assert (
        parse_resource_request(authored, registry=composed)
        .entries["local.scratch"]
        .amount
        == 10
    )
    with pytest.raises(RuntimeResourceError, match="unregistered"):
        parse_resource_request(authored)
    with pytest.raises(RuntimeResourceError, match="already registered"):
        custom.with_validator("local.scratch", _validate_local_scratch)
    with pytest.raises(RuntimeResourceError, match="already registered"):
        DEFAULT_RESOURCE_VALIDATOR_REGISTRY.compose(
            ResourceValidatorRegistry().with_validator("cpu", _validate_local_scratch)
        )


def test_custom_resource_registry_survives_pipeline_and_runtime_reparse() -> None:
    registry = DEFAULT_RESOURCE_VALIDATOR_REGISTRY.with_validator(
        "stage28.device",
        lambda entry, path: None,
    )
    resources = {
        "entries": {
            "stage28.device": {
                "kind": "stage28.device",
                "amount": 1,
                "attributes": {"model": "v1"},
            }
        }
    }
    config = {
        "pipeline": {
            "stages": [
                {
                    "name": "build",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                    },
                    "resources": resources,
                    "outputs": {
                        "data": {
                            "artifact_type": "json",
                            "codec_key": "json.v1",
                        }
                    },
                }
            ]
        },
        "runtime": {"stage_options": {"build": {"resources": resources}}},
    }

    with pytest.raises(RuntimeResourceError, match="unregistered"):
        validate_pipeline_config(config)
    result = validate_pipeline_config(config, registry=registry)
    stage = result.spec.get_stage("build")
    assert stage.resources == resources
    assert stage.resource_request.entries["stage28.device"].amount == 1

    with pytest.raises(RuntimeResourceError, match="unregistered"):
        merge_config_run_options(config, known_stage_ids=("build",))
    options = merge_config_run_options(
        config,
        known_stage_ids=("build",),
        registry=registry,
    )
    stage_options = cast(StageRuntimeOptions, options.stage_options["build"])
    runtime_resources = cast(ResourceRequest, stage_options.resources)
    assert runtime_resources.entries["stage28.device"].amount == 1


def test_runtime_request_round_trips_local_runtime_with_entry_resources() -> None:
    request = RuntimeRequest(
        kind=RuntimeKind.LOCAL,
        resources=ResourceRequest(entries={"cpu": ResourceEntry(kind="cpu", amount=1)}),
        metadata={"note": "local"},
    )

    assert request.to_dict() == {
        "schema_version": 1,
        "kind": "LOCAL",
        "resources": {
            "schema_version": RESOURCE_SCHEMA_VERSION,
            "entries": {
                "cpu": {
                    "kind": "cpu",
                    "amount": 1,
                    "unit": None,
                    "attributes": {},
                },
            },
        },
        "metadata": {"note": "local"},
    }
    assert RuntimeRequest.from_dict(request.to_dict()) == request
    assert parse_runtime_request(request.to_dict()) == request


def test_runtime_request_rejects_nested_old_resource_documents() -> None:
    with pytest.raises(RuntimeResourceError):
        RuntimeRequest.from_dict(
            {
                "schema_version": 1,
                "kind": "LOCAL",
                "resources": {
                    "schema_version": 1,
                    "cpus": 1,
                    "memory_mb": None,
                    "gpus": None,
                    "custom": {},
                },
                "metadata": {},
            }
        )


@pytest.mark.parametrize(
    "runtime",
    [
        {"schema_version": 1, "kind": "SLURM", "resources": {}, "metadata": {}},
        {
            "schema_version": 1,
            "kind": "LOCAL",
            "resources": {},
            "metadata": {},
            "executor": "local",
        },
        {
            "schema_version": 1,
            "kind": "LOCAL",
            "resources": {},
            "metadata": {},
            "timeout": 5,
        },
        {
            "schema_version": 1,
            "kind": "LOCAL",
            "resources": {},
            "metadata": {},
            "container": {},
        },
    ],
)
def test_runtime_request_rejects_unsupported_runtime_fields(
    runtime: dict[str, object],
) -> None:
    with pytest.raises(RuntimeResourceError):
        RuntimeRequest.from_dict(runtime)
