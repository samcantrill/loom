"""Unit tests for executor descriptor capability validation."""

from __future__ import annotations

from typing import Any, cast

import pytest

from loom.pipeline import (
    DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY,
    CapabilityDiagnostic,
    CapabilitySeverity,
    CapabilityValidationResult,
    ExecutorDescriptor,
    ExecutorDescriptorRegistry,
    ResourceCapability,
    ResourceEnforcementExpectation,
    ResourceEntry,
    ResourceRequest,
    ResourceSupportLevel,
    RunOptions,
    StageRuntimeOptions,
    resolve_executor_descriptor,
    validate_executor_capabilities,
)
from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import (
    DEFAULT_RESOURCE_VALIDATOR_REGISTRY,
    ResourceValidatorRegistry,
)


pytestmark = pytest.mark.unit


def test_resource_capability_defaults_and_serialization_are_plain_data() -> None:
    supported = ResourceCapability(
        support_level=ResourceSupportLevel.SUPPORTED,
        details={"z": ["last"], "a": {"nested": True}},
    )
    advisory = ResourceCapability(support_level="advisory")
    ignored = ResourceCapability(support_level="ignored")
    unsupported = ResourceCapability(support_level="unsupported")

    assert supported.enforcement is ResourceEnforcementExpectation.ENFORCED
    assert supported.severity is CapabilitySeverity.INFO
    assert advisory.enforcement is ResourceEnforcementExpectation.BEST_EFFORT
    assert advisory.severity is CapabilitySeverity.WARNING
    assert ignored.enforcement is ResourceEnforcementExpectation.NOT_ENFORCED
    assert ignored.severity is CapabilitySeverity.WARNING
    assert unsupported.enforcement is ResourceEnforcementExpectation.NOT_APPLICABLE
    assert unsupported.severity is CapabilitySeverity.ERROR
    assert supported.to_dict() == {
        "support_level": "supported",
        "enforcement": "enforced",
        "severity": "info",
        "details": {"a": {"nested": True}, "z": ["last"]},
    }
    assert ResourceCapability.from_dict(supported.to_dict()) == supported
    with pytest.raises(TypeError):
        cast(Any, supported.details)["a"] = {}


def test_executor_descriptor_strips_names_and_serializes_deterministically() -> None:
    descriptor = ExecutorDescriptor(
        name=" local ",
        resource_capabilities={
            "memory": ResourceCapability(support_level="ignored"),
            "cpu": {"support_level": "supported"},
        },
        adapter_namespaces=["slurm", "docker"],
        details={"z": 1, "a": 2},
    )

    assert descriptor.name == "local"
    assert tuple(descriptor.resource_capabilities) == ("cpu", "memory")
    assert descriptor.adapter_namespaces == ("docker", "slurm")
    assert descriptor.to_dict()["name"] == "local"
    assert list(
        cast(dict[str, object], descriptor.to_dict()["resource_capabilities"])
    ) == [
        "cpu",
        "memory",
    ]
    assert ExecutorDescriptor.from_dict(descriptor.to_dict()) == descriptor


def test_descriptor_rejects_duplicate_adapter_namespaces() -> None:
    with pytest.raises(RuntimeResourceError, match="duplicate namespace"):
        ExecutorDescriptor(name="local", adapter_namespaces=["slurm", " slurm "])


def test_registry_lookup_serialization_and_composition_are_deterministic() -> None:
    local = ExecutorDescriptor(name=" local ")
    batch = ExecutorDescriptor(name="batch")
    registry = ExecutorDescriptorRegistry({" local ": local})

    assert registry.resolve(None) == local
    assert registry.resolve(" local ") == local
    assert registry.to_dict() == {
        "descriptors": {
            "local": local.to_dict(),
        }
    }
    assert ExecutorDescriptorRegistry.from_dict(registry.to_dict()) == registry

    composed = registry.compose(ExecutorDescriptorRegistry({"batch": batch}))
    assert tuple(composed.descriptors) == ("batch", "local")
    assert composed.resolve("batch") == batch
    with pytest.raises(RuntimeResourceError, match="already registered"):
        registry.with_descriptor(ExecutorDescriptor(name="local"))
    with pytest.raises(RuntimeResourceError, match="already registered"):
        ExecutorDescriptorRegistry(
            {"local": local, " local ": ExecutorDescriptor(name="local")}
        )


def test_default_registry_contains_import_light_builtin_descriptors() -> None:
    descriptor = resolve_executor_descriptor(
        registry=DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY
    )

    assert tuple(DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.descriptors) == (
        "docker",
        "local",
        "slurm-afterok",
        "slurm-single-job",
        "subprocess",
    )
    assert descriptor.name == "local"
    assert descriptor.adapter_namespaces == ()
    assert set(descriptor.resource_capabilities) == {"cpu", "memory", "gpu"}
    capabilities = cast(dict[str, ResourceCapability], descriptor.resource_capabilities)
    assert {
        kind: capability.to_dict()["support_level"]
        for kind, capability in capabilities.items()
    } == {"cpu": "ignored", "memory": "ignored", "gpu": "ignored"}
    subprocess_descriptor = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve("subprocess")
    assert subprocess_descriptor.details["process_isolating"] is True
    assert subprocess_descriptor.details["serial"] is True
    docker_descriptor = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve("docker")
    assert docker_descriptor.adapter_namespaces == ("container", "docker")
    assert docker_descriptor.details["built_in"] is True
    assert docker_descriptor.details["containerized"] is True
    assert docker_descriptor.details["docker_cli"] is True
    assert docker_descriptor.details["docker_sdk_dependency"] is False
    assert docker_descriptor.details["security_sandbox"] is False
    assert docker_descriptor.details["requires_prepared_worker_request"] is True
    assert {
        kind: capability.to_dict()["support_level"]
        for kind, capability in cast(
            dict[str, ResourceCapability],
            docker_descriptor.resource_capabilities,
        ).items()
    } == {"cpu": "supported", "memory": "supported", "gpu": "unsupported"}
    assert {
        kind: capability.to_dict()["enforcement"]
        for kind, capability in cast(
            dict[str, ResourceCapability],
            docker_descriptor.resource_capabilities,
        ).items()
    } == {"cpu": "best_effort", "memory": "best_effort", "gpu": "not_applicable"}
    slurm_descriptor = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve("slurm-single-job")
    assert slurm_descriptor.adapter_namespaces == ("slurm",)
    assert slurm_descriptor.details["dry_run_only"] is False
    assert slurm_descriptor.details["live_submission"] is True
    assert slurm_descriptor.details["scheduler_commands"] is True
    afterok_descriptor = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve("slurm-afterok")
    assert afterok_descriptor.details["dry_run_only"] is False
    assert afterok_descriptor.details["live_submission"] is True
    assert afterok_descriptor.details["scheduler_commands"] is True
    assert {
        kind: capability.to_dict()["support_level"]
        for kind, capability in cast(
            dict[str, ResourceCapability],
            slurm_descriptor.resource_capabilities,
        ).items()
    } == {"cpu": "supported", "memory": "supported", "gpu": "supported"}


def test_unknown_executor_returns_error_result_and_raise_for_errors_is_strict() -> None:
    result = validate_executor_capabilities(RunOptions(executor=" slurm "))

    assert not result.ok
    assert result.has_errors
    assert result.to_dict()["diagnostics"] == [
        {
            "path": "RunOptions.executor",
            "severity": "error",
            "code": "executor.unknown",
            "message": "executor 'slurm' is not registered",
            "executor": "slurm",
            "stage_id": None,
            "resource_kind": None,
            "adapter_namespace": None,
            "support_level": None,
            "enforcement": None,
            "details": {},
        }
    ]
    with pytest.raises(
        RuntimeResourceError, match="executor.unknown at RunOptions.executor"
    ):
        result.raise_for_errors()


def test_slurm_descriptor_claims_adapter_namespace_and_resources() -> None:
    result = validate_executor_capabilities(
        RunOptions(
            executor="slurm-afterok",
            adapter_options={"slurm": {"launcher_argv": ["loom"]}},
            stage_options={
                "train": StageRuntimeOptions(
                    resources=ResourceRequest(
                        entries={
                            "cpu": ResourceEntry(kind="cpu", amount=2),
                            "memory": ResourceEntry(
                                kind="memory", amount=4, unit="GiB"
                            ),
                            "gpu": ResourceEntry(kind="gpu", amount=1),
                        }
                    )
                )
            },
        )
    )

    assert result.ok
    diagnostics = cast(list[dict[str, object]], result.to_dict()["diagnostics"])
    assert [(item["code"], item["resource_kind"]) for item in diagnostics] == [
        ("resource.supported", "cpu"),
        ("resource.supported", "gpu"),
        ("resource.supported", "memory"),
    ]


def test_docker_descriptor_claims_container_namespaces_and_rejects_gpu() -> None:
    result = validate_executor_capabilities(
        RunOptions(
            executor="docker",
            adapter_options={
                "container": {"image": {"reference": "python:3.12"}},
                "docker": {},
            },
            stage_options={
                "train": StageRuntimeOptions(
                    resources=ResourceRequest(
                        entries={
                            "cpu": ResourceEntry(kind="cpu", amount=2),
                            "memory": ResourceEntry(
                                kind="memory",
                                amount=4,
                                unit="GiB",
                            ),
                            "gpu": ResourceEntry(kind="gpu", amount=1),
                        }
                    )
                )
            },
        )
    )

    assert not result.ok
    diagnostics = cast(list[dict[str, object]], result.to_dict()["diagnostics"])
    assert [
        (
            item["resource_kind"],
            item["code"],
            item["severity"],
            item["enforcement"],
        )
        for item in diagnostics
    ] == [
        ("cpu", "resource.supported", "info", "best_effort"),
        ("gpu", "resource.unsupported", "error", "not_applicable"),
        ("memory", "resource.supported", "info", "best_effort"),
    ]
    assert "adapter_namespace.unclaimed" not in {
        item["code"] for item in diagnostics
    }


def test_whitespace_only_executor_returns_unknown_executor_diagnostic() -> None:
    result = validate_executor_capabilities(RunOptions(executor="   "))

    assert not result.ok
    assert result.has_errors
    assert result.to_dict()["diagnostics"] == [
        {
            "path": "RunOptions.executor",
            "severity": "error",
            "code": "executor.unknown",
            "message": "selected executor name must be a non-empty string after stripping",
            "executor": None,
            "stage_id": None,
            "resource_kind": None,
            "adapter_namespace": None,
            "support_level": None,
            "enforcement": None,
            "details": {},
        }
    ]


def test_local_resource_requests_warn_without_failing_validation() -> None:
    options = RunOptions(
        stage_options={
            "train": StageRuntimeOptions(
                resources=ResourceRequest(
                    entries={
                        "memory": ResourceEntry(kind="memory", amount=2, unit="GiB"),
                        "cpu": ResourceEntry(kind="cpu", amount=2),
                        "gpu": ResourceEntry(kind="gpu", amount=0),
                    }
                )
            )
        }
    )

    result = validate_executor_capabilities(options)

    assert result.ok
    result.raise_for_errors()
    diagnostics = cast(list[dict[str, object]], result.to_dict()["diagnostics"])
    assert [diagnostic["code"] for diagnostic in diagnostics] == [
        "resource.ignored",
        "resource.ignored",
        "resource.ignored",
    ]
    assert [diagnostic["resource_kind"] for diagnostic in diagnostics] == [
        "cpu",
        "gpu",
        "memory",
    ]
    assert {diagnostic["severity"] for diagnostic in diagnostics} == {"warning"}
    assert {diagnostic["enforcement"] for diagnostic in diagnostics} == {"not_enforced"}


def test_omitted_resource_capability_uses_descriptor_fallback_policy() -> None:
    registry = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.compose(
        ExecutorDescriptorRegistry(
            {
                "batch": ExecutorDescriptor(
                    name="batch",
                    resource_capabilities={
                        "cpu": ResourceCapability(support_level="supported"),
                    },
                )
            }
        )
    )
    options = RunOptions(
        executor="batch",
        stage_options={
            "train": StageRuntimeOptions(
                resources=ResourceRequest(
                    entries={
                        "cpu": ResourceEntry(kind="cpu", amount=2),
                        "memory": ResourceEntry(kind="memory", amount=2, unit="GiB"),
                    }
                )
            )
        },
    )

    result = validate_executor_capabilities(options, registry=registry)

    assert not result.ok
    diagnostics = cast(list[dict[str, object]], result.to_dict()["diagnostics"])
    assert [
        (item["resource_kind"], item["code"], item["severity"]) for item in diagnostics
    ] == [
        ("cpu", "resource.supported", "info"),
        ("memory", "resource.unsupported", "error"),
    ]


def test_fake_descriptor_can_claim_warn_ignore_or_reject_registered_kinds() -> None:
    def _validate_scratch(entry: ResourceEntry, path: str) -> None:
        if entry.amount <= 0:
            raise RuntimeResourceError(f"{path}.amount must be positive")

    resource_registry = DEFAULT_RESOURCE_VALIDATOR_REGISTRY.compose(
        ResourceValidatorRegistry().with_validator("test.scratch", _validate_scratch)
    )
    descriptor_registry = ExecutorDescriptorRegistry(
        {
            "fake": ExecutorDescriptor(
                name="fake",
                resource_capabilities={
                    "cpu": ResourceCapability(support_level="supported"),
                    "memory": ResourceCapability(support_level="advisory"),
                    "gpu": ResourceCapability(support_level="ignored"),
                    "test.scratch": ResourceCapability(support_level="unsupported"),
                },
            )
        }
    )
    options = RunOptions(
        executor="fake",
        stage_options={
            "train": StageRuntimeOptions(
                resources=ResourceRequest(
                    entries={
                        "cpu": ResourceEntry(kind="cpu", amount=2),
                        "memory": ResourceEntry(kind="memory", amount=2, unit="GiB"),
                        "gpu": ResourceEntry(kind="gpu", amount=1),
                        "test.scratch": ResourceEntry(
                            kind="test.scratch",
                            amount=10,
                            unit="GiB",
                        ),
                    },
                    validator_registry=resource_registry,
                )
            )
        },
    )

    result = validate_executor_capabilities(options, registry=descriptor_registry)

    assert not result.ok
    diagnostics = cast(list[dict[str, object]], result.to_dict()["diagnostics"])
    assert [
        (item["resource_kind"], item["code"], item["severity"]) for item in diagnostics
    ] == [
        ("cpu", "resource.supported", "info"),
        ("gpu", "resource.ignored", "warning"),
        ("memory", "resource.advisory", "warning"),
        ("test.scratch", "resource.unsupported", "error"),
    ]


def test_unclaimed_adapter_namespaces_warn_without_payload_inspection() -> None:
    registry = ExecutorDescriptorRegistry(
        {
            "batch": ExecutorDescriptor(
                name="batch",
                adapter_namespaces=("docker",),
            )
        }
    )
    options = RunOptions(
        executor="batch",
        adapter_options={
            "docker": {"image": "python"},
            "slurm": {"account": "not inspected"},
        },
        stage_options={
            "train": StageRuntimeOptions(
                adapter_options={
                    "docker": {"env": {"TOKEN": "not inspected"}},
                    "slurm": {"partition": "debug"},
                }
            )
        },
    )

    result = validate_executor_capabilities(options, registry=registry)

    assert result.ok
    diagnostics = cast(list[dict[str, object]], result.to_dict()["diagnostics"])
    assert [(item["path"], item["adapter_namespace"]) for item in diagnostics] == [
        ("RunOptions.adapter_options['slurm']", "slurm"),
        ("RunOptions.stage_options['train'].adapter_options['slurm']", "slurm"),
    ]
    assert {item["code"] for item in diagnostics} == {"adapter_namespace.unclaimed"}
    assert "not inspected" not in repr(diagnostics)


def test_adapter_namespace_payloads_must_only_be_plain_data_from_run_options() -> None:
    with pytest.raises(RuntimeResourceError, match="plain-data-compatible"):
        RunOptions(adapter_options=cast(Any, {"slurm": object()}))


def test_capability_validation_result_sorts_diagnostics_and_raises_only_errors() -> (
    None
):
    warning = CapabilityDiagnostic(
        path="RunOptions.stage_options['z'].adapter_options['slurm']",
        severity="warning",
        code="adapter_namespace.unclaimed",
        message="z warning",
        adapter_namespace="slurm",
    )
    error = CapabilityDiagnostic(
        path="RunOptions.executor",
        severity="error",
        code="executor.unknown",
        message="unknown",
        executor="missing",
    )
    result = CapabilityValidationResult([warning, error])

    assert not CapabilityValidationResult([warning]).has_errors
    CapabilityValidationResult([warning]).raise_for_errors()
    assert [
        item["path"]
        for item in cast(list[dict[str, object]], result.to_dict()["diagnostics"])
    ] == [
        "RunOptions.executor",
        "RunOptions.stage_options['z'].adapter_options['slurm']",
    ]
    with pytest.raises(
        RuntimeResourceError, match="executor.unknown at RunOptions.executor"
    ):
        result.raise_for_errors()
