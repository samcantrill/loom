"""Package-level import smoke tests."""

import re
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest

import loom

pytestmark = pytest.mark.package


def test_package_imports() -> None:
    assert loom.__version__


def test_package_declares_public_exports() -> None:
    assert loom.__all__ == [
        "__version__",
        "ResourceRef",
        "InMemoryManifest",
        "ManifestView",
        "Record",
        "ArtifactAddress",
        "ArtifactRef",
        "Fingerprint",
        "hash_mapping",
    ]


def test_import_lom_io_package() -> None:
    import loom.io

    assert loom.io.__all__


def test_import_loom_diagnostics_public_api() -> None:
    import loom.diagnostics

    assert loom.diagnostics.__all__ == [
        "PreflightStatus",
        "PreflightCheckStatus",
        "PreflightSeverity",
        "PreflightGroup",
        "ArtifactBackendPreflightTarget",
        "CleanupPreflightTarget",
        "PreflightCheckResult",
        "PreflightResult",
        "PreflightRequest",
        "PreflightError",
        "BackendCapabilitiesResult",
        "BackendDiagnosticsError",
        "BackendInspectionResult",
        "inspect_backend",
        "inspect_backend_capabilities",
        "parse_projection_revision",
        "run_preflight",
        "RunInspectionAxis",
        "RunInspectionAxisName",
        "RunInspectionFailure",
        "RunInspectionFailureCode",
        "RunInspectionLocation",
        "RunInspectionProjection",
        "RunInspectionResponse",
        "RunInspectionResult",
        "RunInspectionStage",
        "RunInspectionTruncation",
        "RunLocationReachability",
        "inspect_run",
        "decode_run_inspection_response",
        "projection_callable",
    ]


def test_import_loom_queue_public_api() -> None:
    import loom.queue
    from loom.queue import (
        ManagedLocalPreparationReceipt,
        SessionReplacementRequest,
        prepare_managed_local_run,
    )

    assert "QueueItem" in loom.queue.__all__
    assert "QueueService" in loom.queue.__all__
    assert "QueueClient" in loom.queue.__all__
    assert "QueueController" in loom.queue.__all__
    assert "QueueCycleResult" in loom.queue.__all__
    assert "QueueDispatchDisposition" in loom.queue.__all__
    assert "QueueSelectionCandidate" in loom.queue.__all__
    assert "QueueSelectionContext" in loom.queue.__all__
    assert "QueueSelectionDisposition" in loom.queue.__all__
    assert "QueueSelectionDecision" in loom.queue.__all__
    assert "QueueSelectionPolicy" in loom.queue.__all__
    assert "ResourceAssignmentProvider" in loom.queue.__all__
    assert "StaticSlotAssignmentProvider" in loom.queue.__all__
    assert "load_queue_spec" in loom.queue.__all__
    assert "SQLiteQueueRepository" in loom.queue.__all__
    assert "validate_one_queue_per_pool" in loom.queue.__all__
    assert "SessionReplacementRequest" in loom.queue.__all__
    assert "ManagedLocalPreparationReceipt" in loom.queue.__all__
    assert "prepare_managed_local_run" in loom.queue.__all__
    assert ManagedLocalPreparationReceipt
    assert callable(prepare_managed_local_run)
    assert (
        SessionReplacementRequest(
            "replace-agent", "agent-a", "lost agent root"
        ).agent_id
        == "agent-a"
    )


def test_import_managed_local_queue_runtime_is_removed() -> None:
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("loom.queue.managed_local")


def test_import_local_gpu_planning_is_explicit_and_does_not_probe_hardware() -> None:
    import loom.queue
    from loom.queue.gpu import (
        LocalGpuDevice,
        LocalGpuLink,
        LocalGpuPoolLayout,
        LocalGpuPoolPlan,
        plan_local_gpu_pool,
    )

    assert LocalGpuDevice
    assert LocalGpuLink
    assert LocalGpuPoolLayout.grouped
    assert LocalGpuPoolPlan
    assert plan_local_gpu_pool
    assert "LocalGpuDevice" not in loom.queue.__all__


def test_package_includes_typing_marker() -> None:
    assert files("loom").joinpath("py.typed").is_file()


def test_project_metadata_exposes_loom_console_script_entry_point() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["scripts"] == {"loom": "loom.cli.main:main"}
    assert "gui-scripts" not in project


def test_weave_dependency_source_is_revision_pinned_and_locked() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    weave_source = pyproject["tool"]["uv"]["sources"]["weave"]
    git_url = "https://github.com/samcantrill/weave.git"

    assert weave_source["git"] == git_url
    revision = weave_source["rev"]
    assert re.fullmatch(r"[0-9a-f]{40}", revision)

    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    loom_package = next(
        package for package in lock["package"] if package["name"] == "loom"
    )
    weave_package = next(
        package for package in lock["package"] if package["name"] == "weave"
    )
    pinned_url = f"{git_url}?rev={revision}"

    weave_requirements = tuple(
        requirement
        for requirement in loom_package["metadata"]["requires-dist"]
        if requirement["name"] == "weave"
    )
    assert len(weave_requirements) == 2
    assert all(requirement["git"] == pinned_url for requirement in weave_requirements)
    assert weave_package["source"]["git"] == f"{pinned_url}#{revision}"
