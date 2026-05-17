"""Contracts for runtime profile serialization and merge behavior."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from textwrap import dedent
from typing import cast

import pytest

from loom.pipeline import (
    ResourceEntry,
    ResourceRequest,
    RunOptions,
    StageRuntimeOptions,
    merge_run_options,
)
from loom.pipeline.runtime import RuntimeProfileCollection
from loom.serialization import stable_json_dumps


pytestmark = pytest.mark.contract


def test_runtime_profiles_are_plain_data_and_deterministically_serialized() -> None:
    profiles = RuntimeProfileCollection.from_dict(
        {
            "cluster": {
                "executor": "slurm",
                "tags": {"mode": "cluster"},
                "slurm": {"partition": "debug"},
            },
            "local": {
                "executor": "local",
                "adapter_options": {"local": {"capture_logs": True}},
            },
        }
    )

    document = profiles.to_dict()
    assert stable_json_dumps(document)
    assert RuntimeProfileCollection.from_dict(document).to_dict() == document
    assert document == {
        "cluster": {
            "adapter_options": {"slurm": {"partition": "debug"}},
            "executor": "slurm",
            "tags": {"mode": "cluster"},
        },
        "local": {
            "adapter_options": {"local": {"capture_logs": True}},
            "executor": "local",
        },
    }


def test_runtime_profiles_accept_container_and_docker_adapter_namespaces() -> None:
    profiles = RuntimeProfileCollection.from_dict(
        {
            "containerized": {
                "executor": "docker",
                "container": {
                    "image": {"reference": "python:3.12"},
                    "workdir": "/workspace",
                },
                "docker": {"pull": "never"},
            }
        }
    )

    assert stable_json_dumps(profiles.to_dict())
    assert profiles.to_dict() == {
        "containerized": {
            "adapter_options": {
                "container": {
                    "image": {"reference": "python:3.12"},
                    "workdir": "/workspace",
                },
                "docker": {"pull": "never"},
            },
            "executor": "docker",
        }
    }


def test_runtime_profiles_accept_container_build_adapter_namespace() -> None:
    profiles = RuntimeProfileCollection.from_dict(
        {
            "hpc": {
                "executor": "slurm-afterok",
                "container_build": {
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
                        }
                    }
                },
                "container": {"target": "analysis-env"},
                "apptainer": {"cleanenv": True},
            }
        }
    )

    assert stable_json_dumps(profiles.to_dict())
    assert profiles.to_dict() == {
        "hpc": {
            "adapter_options": {
                "apptainer": {"cleanenv": True},
                "container": {"target": "analysis-env"},
                "container_build": {
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
                        }
                    }
                },
            },
            "executor": "slurm-afterok",
        }
    }


def test_runtime_profile_merge_returns_normalized_run_options_contract() -> None:
    result = merge_run_options(
        base={
            "profile": "cluster",
            "tags": {"team": "base"},
            "stage_options": {
                "train": {
                    "resources": {"entries": {"cpu": {"kind": "cpu", "amount": 2}}}
                }
            },
        },
        profiles={
            "cluster": {
                "executor": "slurm",
                "tags": {"mode": "profile"},
                "slurm": {"partition": "debug"},
                "stage_options": {
                    "train": {
                        "resources": {
                            "entries": {
                                "memory": {
                                    "kind": "memory",
                                    "amount": 1024,
                                    "unit": "MiB",
                                }
                            }
                        }
                    }
                },
            }
        },
        explicit={
            "tags": {"owner": "explicit"},
            "adapter_options": {"slurm": {"partition": "explicit"}},
            "stage_options": {
                "train": {
                    "resources": {"entries": {"cpu": {"kind": "cpu", "amount": 4}}}
                }
            },
        },
    )

    assert isinstance(result, RunOptions)
    assert stable_json_dumps(result.to_dict())
    assert result.profile == "cluster"
    assert result.executor == "slurm"
    assert result.tags == {
        "mode": "profile",
        "owner": "explicit",
        "team": "base",
    }
    assert result.adapter_options == {"slurm": {"partition": "explicit"}}
    stage_options = cast(Mapping[str, StageRuntimeOptions], result.stage_options)
    train_resources = stage_options["train"].resources
    assert cast_resource_request(train_resources).entries == {
        "cpu": ResourceEntry(kind="cpu", amount=4),
        "memory": ResourceEntry(kind="memory", amount=1024, unit="MiB"),
    }


def test_runtime_profile_merge_accepts_typed_run_options_as_fully_supplied() -> None:
    result = merge_run_options(
        base={"profile": "cluster", "executor": "slurm", "tags": {"team": "base"}},
        profiles={"cluster": {"executor": "local"}},
        explicit=RunOptions(),
    )

    assert result.profile is None
    assert result.executor is None
    assert result.tags == {"team": "base"}


def test_runtime_profile_merge_does_not_import_outer_runtime_layers() -> None:
    script = dedent(
        """
        import sys

        from loom.pipeline.runtime import merge_run_options

        result = merge_run_options(
            base={"profile": "cluster"},
            profiles={"cluster": {"executor": "local"}},
        )
        assert result.executor == "local"

        for forbidden in (
            "loom.cli",
            "loom.config",
            "loom.diagnostics",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "loom.plugins",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through runtime profiles")
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


def cast_resource_request(value: object) -> ResourceRequest:
    assert isinstance(value, ResourceRequest)
    return value
