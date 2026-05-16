"""Unit tests for shared container execution records."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent
from typing import Any, cast

import pytest

from loom.pipeline.executors.containers import (
    REDACTED_VALUE,
    ContainerEnvironment,
    ContainerImageReference,
    ContainerMount,
    ContainerMountMode,
    ContainerOptionError,
    ContainerOptions,
    ContainerResourceIntent,
    parse_container_options,
    summarize_path_parity,
    validate_reserved_docker_options,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.runtime import ResourceCapability
from loom.serialization import PlainData, stable_json_dumps


pytestmark = pytest.mark.unit


def test_container_options_round_trip_and_redacted_projection() -> None:
    options = parse_container_options(
        {
            "image": {"reference": "python:3.12-slim"},
            "workdir": "/workspace",
            "mounts": [
                {"source": "/workspace", "target": "/workspace", "mode": "rw"},
                {"source": "/readonly", "target": "/readonly", "mode": "ro"},
            ],
            "environment": {
                "variables": {"TOKEN": "secret", "MODE": "test"},
                "required_host_variables": ["HOME"],
            },
        }
    )

    document = options.to_dict()
    assert stable_json_dumps(document)
    assert ContainerOptions.from_dict(document).to_dict() == document
    assert document == {
        "image": {"reference": "python:3.12-slim"},
        "workdir": "/workspace",
        "mounts": [
            {"mode": "rw", "source": "/workspace", "target": "/workspace"},
            {"mode": "ro", "source": "/readonly", "target": "/readonly"},
        ],
        "environment": {
            "variables": {"MODE": "test", "TOKEN": "secret"},
            "required_host_variables": ["HOME"],
        },
        "resources": None,
    }

    redacted = options.to_redacted_metadata()
    assert redacted["environment"] == {
        "variable_names": ["MODE", "TOKEN"],
        "variables": {"MODE": REDACTED_VALUE, "TOKEN": REDACTED_VALUE},
        "required_host_variables": ["HOME"],
    }
    assert "secret" not in repr(redacted)
    environment = cast(ContainerEnvironment, options.environment)
    with pytest.raises(TypeError):
        cast(Any, environment.variables)["NEW"] = "value"


def test_container_records_reject_invalid_mounts_and_options() -> None:
    with pytest.raises(ContainerOptionError, match="reference"):
        ContainerImageReference(" ")
    with pytest.raises(ContainerOptionError, match="absolute"):
        ContainerMount(source="relative", target="/work", mode="rw")
    with pytest.raises(ContainerOptionError, match="absolute container path"):
        ContainerMount(source="/work", target="relative", mode="rw")
    with pytest.raises(ContainerOptionError, match="container root"):
        ContainerMount(source="/work", target="/", mode="rw")
    with pytest.raises(ContainerOptionError, match="path parts"):
        ContainerMount(source="/work", target="/work/../other", mode="rw")
    with pytest.raises(ContainerOptionError, match="one of: ro, rw"):
        ContainerMount(source="/work", target="/work", mode="write")
    with pytest.raises(ContainerOptionError, match="duplicate target"):
        ContainerOptions(
            image="python",
            mounts=(
                ContainerMount(source="/a", target="/same", mode="ro"),
                ContainerMount(source="/b", target="/same", mode="rw"),
            ),
        )
    with pytest.raises(ContainerOptionError, match="unknown field"):
        parse_container_options({"image": "python", "privileged": True})


def test_container_environment_requires_explicit_strings() -> None:
    environment = ContainerEnvironment.from_dict(
        {
            "required_host_variables": ["B", "A"],
            "variables": {"Z": "last", "A": "first"},
        }
    )

    assert environment.to_dict() == {
        "variables": {"A": "first", "Z": "last"},
        "required_host_variables": ["A", "B"],
    }
    with pytest.raises(ContainerOptionError, match="must be a string"):
        ContainerEnvironment.from_dict({"variables": {"A": 1}})
    with pytest.raises(ContainerOptionError, match="duplicate"):
        ContainerEnvironment(required_host_variables=["HOME", "HOME"])


def test_resource_intent_uses_existing_resource_and_capability_contracts() -> None:
    resources = ResourceRequest(
        entries={
            "cpu": ResourceEntry(kind="cpu", amount=2),
            "memory": ResourceEntry(kind="memory", amount=512, unit="MiB"),
        }
    )
    capabilities = {
        "cpu": ResourceCapability(support_level="supported", enforcement="best_effort"),
        "memory": ResourceCapability(
            support_level="supported",
            enforcement="best_effort",
        ),
    }

    intent = ContainerResourceIntent.from_runtime(resources, capabilities)
    document = intent.to_dict()
    parsed = ContainerResourceIntent.from_dict(document)
    assert parsed is not None

    assert stable_json_dumps(document)
    assert parsed.to_dict() == document
    metadata_entries = cast(
        dict[str, PlainData],
        intent.to_redacted_metadata()["entries"],
    )
    assert metadata_entries["cpu"] == {
        "kind": "cpu",
        "amount": 2,
        "unit": None,
        "attribute_count": 0,
    }
    with pytest.raises(ContainerOptionError, match="missing resource kind"):
        ContainerResourceIntent(entries=resources.entries, capabilities={})


def test_path_parity_summaries_fail_closed_without_translation() -> None:
    ok = summarize_path_parity(
        kind="mount",
        host_path="/runs/example",
        container_path="/runs/example",
        writable_required=True,
    )
    mismatch = summarize_path_parity(
        kind="mount",
        host_path="/runs/example",
        container_path="/container/runs/example",
        writable_required=False,
    )
    invalid = summarize_path_parity(
        kind="mount",
        host_path="relative",
        container_path="/runs/example",
        writable_required=False,
    )

    assert ok.to_dict()["ok"] is True
    assert mismatch.to_dict()["reason"] == (
        "host_path and container_path must match in Stage 17"
    )
    assert invalid.to_dict()["ok"] is False
    assert "absolute" in cast(str, invalid.to_dict()["reason"])


def test_docker_namespace_rejects_generic_container_fields() -> None:
    assert dict(validate_reserved_docker_options({})) == {}
    assert dict(validate_reserved_docker_options({"pull": "never"})) == {
        "pull": "never"
    }
    with pytest.raises(ContainerOptionError, match="adapter_options.container"):
        validate_reserved_docker_options({"image": "python"})


def test_container_records_import_without_docker_or_presentation_layers() -> None:
    script = dedent(
        """
        import sys

        from loom.pipeline.executors.containers import ContainerOptions

        assert ContainerOptions
        for forbidden in (
            "loom.cli",
            "loom.config",
            "loom.diagnostics",
            "loom.pipeline.execution",
            "loom.pipeline.executors.docker",
            "docker",
            "subprocess",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} imported through container records")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_mount_mode_enum_values_are_stable() -> None:
    assert ContainerMountMode.READ_ONLY.value == "ro"
    assert ContainerMountMode.READ_WRITE.value == "rw"
