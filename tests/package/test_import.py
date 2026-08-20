"""Package-level import smoke tests."""

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
    ]


def test_import_loom_queue_public_api() -> None:
    import loom.queue

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


def test_import_managed_local_queue_runtime_is_explicit() -> None:
    import loom.queue
    from loom.queue.managed_local import ManagedLocalQueueRuntime

    assert ManagedLocalQueueRuntime
    assert "ManagedLocalQueueRuntime" not in loom.queue.__all__


def test_package_includes_typing_marker() -> None:
    assert files("loom").joinpath("py.typed").is_file()


def test_project_metadata_exposes_loom_console_script_entry_point() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["scripts"] == {"loom": "loom.cli.main:main"}
    assert "gui-scripts" not in project
