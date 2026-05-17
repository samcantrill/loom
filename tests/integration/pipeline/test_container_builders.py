"""Integration tests for local container build service dispatch."""

from __future__ import annotations

import pytest

from loom.pipeline.executors.containers import (
    FakeContainerBuilder,
    LocalContainerBuildService,
    parse_container_build_options,
)


pytestmark = pytest.mark.integration


def test_local_container_build_service_dispatches_fake_runtime_builders() -> None:
    options = parse_container_build_options(
        {
            "targets": {
                "ci-image": {
                    "runtime": "docker",
                    "source": {"kind": "docker_context", "context_path": "."},
                    "output": {
                        "kind": "docker_image",
                        "reference": "example/ci:latest",
                    },
                    "policy": {"mode": "always"},
                },
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
                    "policy": {"mode": "never"},
                },
            }
        }
    )
    service = LocalContainerBuildService(
        {
            "docker": FakeContainerBuilder("docker"),
            "apptainer": FakeContainerBuilder(
                "apptainer",
                existing_outputs=[".loom/containers/analysis.sif"],
            ),
        }
    )

    results = service.build_options(options, requested_by="integration-test")

    assert [result.target_name for result in results] == ["analysis-env", "ci-image"]
    assert [result.status for result in results] == ["reused", "built"]
    assert "secret" not in repr([result.to_dict() for result in results])
