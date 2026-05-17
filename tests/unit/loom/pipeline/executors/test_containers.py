"""Unit tests for shared container execution records."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent
from typing import Any, cast

import pytest

from loom.pipeline.executors.containers import (
    REDACTED_VALUE,
    ContainerBuildCommandProjection,
    ContainerBuildFailure,
    ContainerBuildOptions,
    ContainerBuildOutputRef,
    ContainerBuildPolicy,
    ContainerBuildRequest,
    ContainerBuildResult,
    ContainerBuildSource,
    ContainerBuildTarget,
    ContainerEnvironment,
    ContainerImageReference,
    ContainerMount,
    ContainerMountMode,
    ContainerOptionError,
    ContainerOptions,
    ContainerResourceIntent,
    build_container_build_key,
    parse_container_build_options,
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
    with pytest.raises(ContainerOptionError, match="ContainerImageReference"):
        parse_container_options({"image": "python"})


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


def test_container_build_targets_round_trip_and_redact_metadata() -> None:
    options = parse_container_build_options(
        {
            "targets": {
                "analysis-env": {
                    "runtime": "apptainer",
                    "source": {
                        "kind": "definition_file",
                        "path": "containers/analysis.def",
                    },
                    "output": {
                        "kind": "apptainer_sif",
                        "path": ".loom/containers/analysis-env.sif",
                        "metadata": {"token": "output-secret"},
                    },
                    "policy": {"mode": "if_stale"},
                    "build_args": {"TOKEN": "secret", "MODE": "test"},
                    "metadata": {"token": "target-secret"},
                },
                "ci-image": {
                    "runtime": "docker",
                    "source": {
                        "kind": "docker_context",
                        "context_path": ".",
                        "recipe_path": "Dockerfile",
                    },
                    "output": {
                        "kind": "docker_image",
                        "reference": "example/ci:latest",
                    },
                    "policy": {"mode": "never"},
                },
            },
            "service": {"mode": "local"},
        }
    )

    document = options.to_dict()
    assert stable_json_dumps(document)
    assert ContainerBuildOptions.from_dict(document).to_dict() == document
    assert tuple(options.targets) == ("analysis-env", "ci-image")

    target = cast(dict[str, ContainerBuildTarget], options.targets)["analysis-env"]
    key = target.build_key()
    assert key == build_container_build_key(target)
    assert key.digest.startswith("sha256:")
    redacted = target.to_redacted_metadata()
    assert redacted["build_arg_names"] == ["MODE", "TOKEN"]
    assert redacted["metadata_keys"] == ["token"]
    redacted_output = cast(dict[str, PlainData], redacted["output"])
    assert redacted_output["metadata_keys"] == ["token"]
    assert "secret" not in repr(redacted)


def test_container_build_request_and_result_records_are_plain_data() -> None:
    target = ContainerBuildTarget(
        name="analysis-env",
        runtime="apptainer",
        source=ContainerBuildSource(kind="definition_file", path="containers/a.def"),
        output=ContainerBuildOutputRef(
            kind="apptainer_sif",
            path=".loom/containers/a.sif",
        ),
        policy=ContainerBuildPolicy(mode="always"),
    )
    request = ContainerBuildRequest(target=target, requested_by="controller")
    command = ContainerBuildCommandProjection(
        argv=["apptainer", "build", REDACTED_VALUE, "containers/a.def"],
        environment_keys=["HOME"],
        build_arg_names=["TOKEN"],
    )
    result = ContainerBuildResult(
        target_name="analysis-env",
        status="built",
        output=target.output,
        build_key=request.build_key,
        command=command,
    )

    assert stable_json_dumps(request.to_dict())
    assert (
        ContainerBuildRequest.from_dict(request.to_dict()).to_dict()
        == request.to_dict()
    )
    assert stable_json_dumps(result.to_dict())
    assert (
        ContainerBuildResult.from_dict(result.to_dict()).to_dict() == result.to_dict()
    )
    command_document = cast(dict[str, PlainData], result.to_dict()["command"])
    assert command_document["argv"] == [
        "apptainer",
        "build",
        REDACTED_VALUE,
        "containers/a.def",
    ]
    assert "TOKEN" in repr(command.to_dict())
    assert "secret" not in repr(result.to_dict())

    failure = ContainerBuildResult(
        target_name="analysis-env",
        status="failed",
        failure=ContainerBuildFailure(
            code="container_build.failed",
            message="build command failed",
            details={"argv": [REDACTED_VALUE]},
        ),
    )
    assert failure.to_dict()["failure"] is not None
    with pytest.raises(ContainerOptionError, match="failure is required"):
        ContainerBuildResult(target_name="analysis-env", status="failed")


def test_container_build_records_reject_invalid_shapes() -> None:
    with pytest.raises(ContainerOptionError, match="definition_file"):
        ContainerBuildSource(kind="definition_file", uri="docker://python")
    with pytest.raises(ContainerOptionError, match="URI scheme"):
        ContainerBuildSource(kind="uri", uri="python:3.12")
    with pytest.raises(ContainerOptionError, match="reference is required"):
        ContainerBuildOutputRef(kind="docker_image", path="image.sif")
    with pytest.raises(ContainerOptionError, match="not compatible"):
        ContainerBuildTarget(
            name="bad",
            runtime="docker",
            source={"kind": "docker_context", "context_path": "."},
            output={"kind": "apptainer_sif", "path": "bad.sif"},
        )
    with pytest.raises(ContainerOptionError, match="one of"):
        ContainerBuildPolicy(mode="missing")
    with pytest.raises(ContainerOptionError, match="whitespace"):
        ContainerBuildTarget(
            name="bad target",
            runtime="apptainer",
            source={"kind": "definition_file", "path": "a.def"},
            output={"kind": "apptainer_sif", "path": "a.sif"},
        )
