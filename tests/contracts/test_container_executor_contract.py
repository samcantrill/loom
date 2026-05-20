"""Contracts for shared container executor records."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent
from typing import cast

import pytest

from loom.pipeline.executors.containers import (
    ContainerBuildOptions,
    ContainerBuildOutputRef,
    ContainerBuildPolicyDecision,
    ContainerBuildTarget,
    FakeContainerBuilder,
    LocalContainerBuildService,
    ContainerOptions,
    ContainerResourceIntent,
    build_container_build_key,
    parse_container_build_options,
    parse_container_options,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.runtime import ResourceCapability
from loom.serialization import PlainData, stable_json_dumps


pytestmark = pytest.mark.contract


def test_container_adapter_options_plain_data_contract_is_stable() -> None:
    options = parse_container_options(
        {
            "image": {"reference": "example/runtime:latest"},
            "workdir": "/workspace",
            "mounts": [{"source": "/workspace", "target": "/workspace", "mode": "rw"}],
            "environment": {
                "variables": {"TOKEN": "secret"},
                "required_host_variables": ["HOME"],
            },
        }
    )

    document = options.to_dict()

    assert stable_json_dumps(document)
    assert ContainerOptions.from_dict(document).to_dict() == document
    assert "secret" not in repr(options.to_redacted_metadata())


def test_container_resource_intent_reuses_resource_and_capability_records() -> None:
    resources = ResourceRequest(entries={"cpu": ResourceEntry(kind="cpu", amount=2)})
    intent = ContainerResourceIntent.from_runtime(
        resources,
        {
            "cpu": ResourceCapability(
                support_level="supported",
                enforcement="best_effort",
            )
        },
    )

    document = intent.to_dict()

    assert stable_json_dumps(document)
    entries = cast(dict[str, PlainData], document["entries"])
    capabilities = cast(dict[str, PlainData], document["capabilities"])
    cpu_entry = cast(dict[str, PlainData], entries["cpu"])
    cpu_capability = cast(dict[str, PlainData], capabilities["cpu"])
    assert cpu_entry["kind"] == "cpu"
    assert cpu_capability["enforcement"] == "best_effort"


def test_container_build_adapter_options_plain_data_contract_is_stable() -> None:
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
                    },
                    "policy": {"mode": "if_stale"},
                    "build_args": {"TOKEN": "secret"},
                }
            }
        }
    )

    document = options.to_dict()

    assert stable_json_dumps(document)
    assert ContainerBuildOptions.from_dict(document).to_dict() == document
    target = cast(dict[str, ContainerBuildTarget], options.targets)["analysis-env"]
    assert build_container_build_key(target).to_dict()["target_name"] == "analysis-env"
    assert "secret" not in repr(target.to_redacted_metadata())


def test_build_output_refs_distinguish_docker_images_from_apptainer_sifs() -> None:
    docker = ContainerBuildOutputRef(
        kind="docker_image",
        reference="example/runtime:latest",
    )
    apptainer = ContainerBuildOutputRef(
        kind="apptainer_sif",
        path=".loom/containers/runtime.sif",
    )

    assert docker.to_dict()["reference"] == "example/runtime:latest"
    assert "path" not in docker.to_dict()
    assert apptainer.to_dict()["path"] == ".loom/containers/runtime.sif"
    assert "reference" not in apptainer.to_dict()


def test_local_container_build_service_contract_uses_shared_results() -> None:
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
                        "path": ".loom/containers/analysis.sif",
                    },
                    "policy": {"mode": "always"},
                }
            }
        }
    )
    service = LocalContainerBuildService(
        {"apptainer": FakeContainerBuilder("apptainer")}
    )

    result = service.build_options(options)[0]
    document = result.to_dict()
    evidence = cast(dict[str, PlainData], document["evidence"])
    metadata = cast(dict[str, PlainData], evidence["metadata"])
    decision = ContainerBuildPolicyDecision.from_dict(metadata["decision"])

    assert stable_json_dumps(document)
    assert result.status == "built"
    assert decision.action == "build"


def test_container_records_do_not_import_docker_or_runtime_presentation_layers() -> (
    None
):
    script = dedent(
        """
        import sys

        import loom.pipeline.executors.containers as containers

        assert containers.ContainerOptions
        assert containers.ContainerBuildOptions
        for forbidden in (
            "loom.cli",
            "weave",
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
