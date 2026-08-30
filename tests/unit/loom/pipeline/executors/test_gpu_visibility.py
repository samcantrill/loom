"""Unit tests for generic GPU container admission helpers."""

from __future__ import annotations

import pytest

from loom.pipeline.executors.apptainer import ApptainerExecOptions, ApptainerOptionError
from loom.pipeline.executors.gpu_visibility import (
    project_apptainer_gpu_options,
    requested_gpu_count,
    validate_cuda_visibility,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest


pytestmark = pytest.mark.unit


def test_visibility_evidence_preserves_opaque_tokens() -> None:
    evidence = validate_cuda_visibility(
        2,
        {"CUDA_VISIBLE_DEVICES": "GPU-abc,MIG-device-7"},
    )

    assert evidence.to_dict() == {
        "requested_gpu_count": 2,
        "cuda_visible_devices": ["GPU-abc", "MIG-device-7"],
    }


@pytest.mark.parametrize(
    "visible",
    (
        None,
        "",
        "-1",
        "0,",
        ",0",
        "0,,1",
        "0, 1",
        "0,0",
        "bad token",
        "-foo",
        ".foo",
    ),
)
def test_visibility_rejects_missing_or_invalid_positive_gpu_bindings(
    visible: str | None,
) -> None:
    environment = {} if visible is None else {"CUDA_VISIBLE_DEVICES": visible}

    with pytest.raises(ApptainerOptionError):
        validate_cuda_visibility(1, environment)


def test_zero_gpu_does_not_claim_or_validate_host_visibility() -> None:
    evidence = validate_cuda_visibility(0, {"CUDA_VISIBLE_DEVICES": "bad token"})

    assert evidence.to_dict() == {
        "requested_gpu_count": 0,
        "cuda_visible_devices": [],
    }


def test_gpu_projection_requires_an_attribute_free_count() -> None:
    resources = ResourceRequest(
        entries={
            "gpu": ResourceEntry(
                kind="gpu",
                amount=1,
                attributes={"models": ["a100"]},
            )
        }
    )

    with pytest.raises(ApptainerOptionError, match="attributes"):
        requested_gpu_count(resources)


def test_gpu_projection_is_additive_and_rejects_rocm_conflict() -> None:
    one_gpu = ResourceRequest(entries={"gpu": ResourceEntry(kind="gpu", amount=1)})

    projected = project_apptainer_gpu_options(
        ApptainerExecOptions(command="singularity", cleanenv=False, fakeroot=True),
        one_gpu,
    )
    assert projected == ApptainerExecOptions(
        command="singularity", cleanenv=False, nv=True, fakeroot=True
    )
    assert project_apptainer_gpu_options(ApptainerExecOptions(nv=True), None).nv is True
    with pytest.raises(ApptainerOptionError, match="rocm"):
        project_apptainer_gpu_options(ApptainerExecOptions(rocm=True), one_gpu)
