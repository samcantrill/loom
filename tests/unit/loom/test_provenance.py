"""Unit tests for provenance models and capture helpers."""

import pytest

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_text
from loom.provenance import (
    ArtifactLineage,
    CommandProvenance,
    EnvironmentProvenance,
    GitProvenance,
    ProvenanceCaptureOptions,
    RunProvenance,
    capture_artifact_lineage,
    capture_command_provenance,
    capture_code_provenance,
    capture_environment_provenance,
    capture_git_provenance,
    capture_run_provenance,
)
from loom.provenance.errors import ProvenanceCaptureError


def test_git_capture_degrades_when_git_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import loom.provenance.git as git_module

    monkeypatch.setattr(git_module.subprocess, "run", lambda *_, **__: (_ for _ in ()).throw(FileNotFoundError()))
    provenance = capture_git_provenance(".", strict=False)
    assert provenance.capture_error is not None
    assert isinstance(provenance, GitProvenance)


def test_git_capture_strict_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    import loom.provenance.git as git_module

    importlib.reload(git_module)

    class _Result:
        returncode = 1
        stderr = "failed"
        stdout = ""

    monkeypatch.setattr(git_module.subprocess, "run", lambda *_, **__: _Result())
    with pytest.raises(ProvenanceCaptureError):
        capture_git_provenance(".", strict=True)


def test_environment_provenance_collects_selected_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAMPLE_TOKEN", "secret")
    captured = capture_environment_provenance(("SAMPLE_TOKEN", "NONE"), include_user=False)
    assert captured.selected_env["SAMPLE_TOKEN"] == "redacted"
    assert "NONE" not in captured.selected_env


def test_command_capture_uses_defaults() -> None:
    cmd = capture_command_provenance()
    assert isinstance(cmd, CommandProvenance)
    assert cmd.argv
    assert cmd.cwd


def test_code_capture_without_package() -> None:
    code = capture_code_provenance()
    assert code.package_name is None
    assert code.package_version is None


def test_artifact_lineage_capture() -> None:
    ref = ArtifactRef(
        artifact_id="stage:out",
        uri="file:///artifacts/out.bin",
        artifact_type="artifact",
        checksum=hash_text("payload"),
        producer_stage="train",
    )
    lineage = capture_artifact_lineage(ref, metadata={"note": "done"})
    assert isinstance(lineage, ArtifactLineage)
    assert lineage.artifact_id == "stage:out"
    assert lineage.metadata["note"] == "done"
    assert lineage.checksum == ref.checksum
    assert lineage.producer_fingerprint is None


def test_capture_run_provenance_aggregates_helpers() -> None:
    options = ProvenanceCaptureOptions(
        capture_git=False,
        capture_environment=False,
        capture_dependencies=False,
        capture_command=False,
    )
    run = capture_run_provenance("run-1", options=options, config={"x": 1})
    assert isinstance(run, RunProvenance)
    assert run.run_id == "run-1"
    assert run.command is None
    assert run.config["x"] == 1
    assert run.code is None
    assert run.environment is None
    assert run.dependencies is None


def test_capture_environment_includes_python_executable() -> None:
    env = capture_environment_provenance()
    assert isinstance(env, EnvironmentProvenance)
    assert env.python_executable is not None
