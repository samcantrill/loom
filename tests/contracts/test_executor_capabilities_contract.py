"""Contracts for executor descriptors and capability validation."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent
from typing import cast

import pytest

from loom.pipeline.execution.models import RunRequest, StageExecutionRequest
from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import ResourceEntry, ResourceRequest, ResourceValidatorRegistry
from loom.pipeline.runtime import (
    CapabilityDiagnostic,
    CapabilitySeverity,
    DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY,
    ExecutorDescriptor,
    ExecutorDescriptorRegistry,
    ResourceCapability,
    RunOptions,
    StageRuntimeOptions,
    validate_executor_capabilities,
)
from loom.serialization import stable_json_dumps


pytestmark = pytest.mark.contract


def test_descriptor_and_diagnostic_documents_are_plain_data() -> None:
    descriptor = ExecutorDescriptor(
        name="batch",
        resource_capabilities={
            "cpu": ResourceCapability(support_level="supported"),
        },
        adapter_namespaces=("batch",),
        details={"owner": "test"},
    )
    diagnostic = CapabilityDiagnostic(
        path="RunOptions.stage_options['train'].resources.entries['cpu']",
        severity=CapabilitySeverity.INFO,
        code="resource.supported",
        message="supported",
        executor="batch",
        stage_id="train",
        resource_kind="cpu",
        support_level="supported",
        enforcement="enforced",
    )

    assert stable_json_dumps(descriptor.to_dict())
    assert stable_json_dumps(diagnostic.to_dict())
    assert stable_json_dumps(validate_executor_capabilities(RunOptions()).to_dict())


def test_fake_descriptor_contract_does_not_change_resource_schema_validation() -> None:
    def _validate_custom(entry: ResourceEntry, path: str) -> None:
        if entry.unit != "GiB":
            raise AssertionError(f"{path}.unit should already be validated by the registry")

    authored = {
        "entries": {
            "contract.scratch": {
                "kind": "contract.scratch",
                "amount": 4,
                "unit": "GiB",
            }
        }
    }
    registry = ExecutorDescriptorRegistry(
        {
            "batch": ExecutorDescriptor(
                name="batch",
                resource_capabilities={
                    "contract.scratch": ResourceCapability(support_level="supported"),
                },
            )
        }
    )

    with pytest.raises(RuntimeResourceError, match="unregistered resource kind"):
        ResourceRequest.from_dict(
            {"schema_version": 2, **authored},
        )

    request = ResourceRequest.from_dict(
        {"schema_version": 2, **authored},
        registry=ResourceValidatorRegistry().with_validator(
            "contract.scratch",
            _validate_custom,
        ),
    )
    result = validate_executor_capabilities(
        RunOptions(
            executor="batch",
            stage_options={
                "train": StageRuntimeOptions(resources=request),
            },
        ),
        registry=registry,
    )

    assert result.ok
    diagnostics = cast(list[dict[str, object]], result.to_dict()["diagnostics"])
    assert [(item["code"], item["resource_kind"]) for item in diagnostics] == [
        ("resource.supported", "contract.scratch")
    ]


def test_capability_validation_is_independent_of_preflight_models() -> None:
    result = validate_executor_capabilities(RunOptions(executor="missing"))
    payload = result.to_dict()
    payload_text = repr(payload)

    assert "runtime.options" not in payload_text
    assert "executor.resolve" not in payload_text
    assert "resources.capabilities" not in payload_text
    assert "PreflightGroup" not in payload_text
    assert stable_json_dumps(payload)


def test_default_registry_includes_import_light_subprocess_descriptor() -> None:
    result = validate_executor_capabilities(RunOptions(executor="subprocess"))

    assert result.ok
    descriptor = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve("subprocess")
    assert descriptor.name == "subprocess"
    assert descriptor.details["process_isolating"] is True
    assert descriptor.details["serial"] is True


def test_default_registry_includes_docker_container_descriptor_contract() -> None:
    result = validate_executor_capabilities(
        RunOptions(
            executor="docker",
            adapter_options={
                "container": {"image": {"reference": "python"}},
                "docker": {},
            },
        )
    )

    assert result.ok
    descriptor = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve("docker")
    assert descriptor.name == "docker"
    assert descriptor.adapter_namespaces == ("container", "docker")
    assert descriptor.details["docker_cli"] is True
    assert descriptor.details["docker_sdk_dependency"] is False
    resource_capabilities = cast(
        dict[str, object],
        descriptor.to_dict()["resource_capabilities"],
    )
    gpu_capability = cast(dict[str, object], resource_capabilities["gpu"])
    assert gpu_capability["support_level"] == "unsupported"


def test_runtime_capability_imports_do_not_load_diagnostics_or_executors() -> None:
    script = dedent(
        """
        import sys

        from loom.pipeline.runtime import ExecutorDescriptor, validate_executor_capabilities

        assert ExecutorDescriptor
        assert validate_executor_capabilities
        for forbidden in ("loom.diagnostics", "loom.pipeline.executors", "loom.pipeline.execution"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} imported through capability contracts")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_execution_envelope_exposes_runtime_handoff_without_adapter_lock_in() -> None:
    assert "options" in RunRequest.__dataclass_fields__
    assert "resolved_runtime" in StageExecutionRequest.__dataclass_fields__
    assert "runtime_options" not in StageExecutionRequest.__dataclass_fields__
