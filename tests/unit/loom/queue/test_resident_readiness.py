"""Resident profile qualification uses the selected worker installation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest

from loom.queue._remote_stage_execution import (
    ResidentExecutionProfile,
    ResidentProfileDescriptor,
)
from loom.queue.resident_readiness import (
    ResidentReadinessRequirements,
    qualify_resident_profile,
)


pytestmark = pytest.mark.unit


def _profile(
    root: Path, requirements: ResidentReadinessRequirements | None = None
) -> ResidentExecutionProfile:
    return ResidentExecutionProfile(
        ResidentProfileDescriptor("test", "v1", "project", "environment", "executor"),
        root,
        Path(sys.executable),
        readiness_requirements=requirements or ResidentReadinessRequirements(),
    )


def test_profile_probe_uses_selected_python_and_reports_missing_import(
    tmp_path: Path,
) -> None:
    result = qualify_resident_profile(
        _profile(tmp_path, ResidentReadinessRequirements(imports=("does_not_exist",)))
    )

    assert not result.ok
    assert result.identity is None
    assert result.checks[0].check_id == "packages.required_imports"
    assert result.checks[0].status == "FAIL"


def test_identity_tracks_declared_source_not_path_or_unrelated_files(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        (root / "source").mkdir(parents=True)
        (root / "source" / "module.py").write_text("value = 1\n", encoding="utf-8")
        (root / "notes.txt").write_text("unrelated\n", encoding="utf-8")

    profile_requirements = ResidentReadinessRequirements(
        imports=("loom",), source_roots=("source",)
    )
    initial = qualify_resident_profile(_profile(first, profile_requirements))
    moved = qualify_resident_profile(_profile(second, profile_requirements))
    assert initial.ok and moved.ok
    assert initial.identity == moved.identity

    (second / "notes.txt").write_text("changed unrelated\n", encoding="utf-8")
    unchanged = qualify_resident_profile(_profile(second, profile_requirements))
    assert unchanged.identity == moved.identity

    (second / "source" / "module.py").write_text("value = 2\n", encoding="utf-8")
    changed = qualify_resident_profile(_profile(second, profile_requirements))
    assert changed.identity != moved.identity


def test_profile_probe_timeout_is_a_stable_failure(tmp_path: Path) -> None:
    sleeper = tmp_path / "sleeper"
    sleeper.write_text("#!/bin/sh\n/bin/sleep 60\n", encoding="utf-8")
    sleeper.chmod(0o700)
    profile = replace(_profile(tmp_path), python_executable=sleeper)
    result = qualify_resident_profile(profile)

    assert not result.ok
    assert result.checks[0].check_id == "python.interpreter"
    assert result.checks[0].message == "resident Python probe timed out"
