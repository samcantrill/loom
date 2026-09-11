"""Resident profile qualification uses the selected worker installation."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from loom.queue._remote_stage_execution import (
    ResidentExecutionProfile,
    ResidentProfileDescriptor,
)
from loom.queue.resident_readiness import (
    ResidentReadinessRequirements,
    qualified_resident_profile,
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
    check = next(
        check
        for check in result.checks
        if check.check_id == "packages.required_imports"
    )
    assert check.status == "FAIL"


@pytest.mark.optional_dependency
def test_preparation_qualification_does_not_change_portable_software_identity(
    tmp_path: Path,
) -> None:
    pytest.importorskip("weave")
    ordinary = qualified_resident_profile(_profile(tmp_path))
    preparation = qualified_resident_profile(
        _profile(tmp_path, ResidentReadinessRequirements(preparation=True))
    )
    assert ordinary.readiness_result is not None
    assert not ordinary.readiness_result.preparation_ready
    assert preparation.readiness_result is not None
    assert preparation.readiness_result.preparation_ready
    assert preparation.readiness_identity == ordinary.readiness_identity
    assert preparation.descriptor == ordinary.descriptor


def test_preparation_qualification_checks_the_actual_selected_environment(
    tmp_path: Path,
) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        "import importlib.abc, sys\n"
        "class MissingConfigLoader(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'weave':\n"
        "            raise ModuleNotFoundError('config loader unavailable in this environment')\n"
        "sys.meta_path.insert(0, MissingConfigLoader())\n"
    )
    profile = replace(_profile(tmp_path), environment={"PYTHONPATH": str(tmp_path)})
    ordinary = qualify_resident_profile(profile)
    assert ordinary.ok
    preparation = qualify_resident_profile(
        replace(
            profile,
            readiness_requirements=ResidentReadinessRequirements(preparation=True),
        )
    )
    assert not preparation.ok
    assert not preparation.preparation_ready
    assert (
        next(
            check
            for check in preparation.checks
            if check.check_id == "packages.preparation_imports"
        ).status
        == "FAIL"
    )


@pytest.mark.optional_dependency
def test_staged_qualification_requires_the_selected_installation_handler(
    tmp_path: Path,
) -> None:
    pytest.importorskip("weave")
    ordinary = qualified_resident_profile(_profile(tmp_path))
    staged = qualified_resident_profile(
        _profile(tmp_path, ResidentReadinessRequirements(preparation_staged=True))
    )
    assert staged.readiness_result is not None
    assert staged.readiness_result.preparation_staged_ready
    assert staged.descriptor == ordinary.descriptor

    # Model a selected shared-only installation in its real probe process.
    (tmp_path / "sitecustomize.py").write_text(
        "import loom.queue.preparation as preparation\n"
        "del preparation.resolve_staged_input\n"
    )
    shared_only = replace(_profile(tmp_path), environment={"PYTHONPATH": str(tmp_path)})
    shared = qualify_resident_profile(replace(
        shared_only, readiness_requirements=ResidentReadinessRequirements(preparation=True)
    ))
    assert shared.preparation_ready
    assert not shared.preparation_staged_ready
    unsupported = qualify_resident_profile(replace(
        shared_only,
        readiness_requirements=ResidentReadinessRequirements(preparation_staged=True),
    ))
    assert not unsupported.ok
    assert not unsupported.preparation_staged_ready
    assert next(
        check for check in unsupported.checks
        if check.check_id == "packages.preparation_staged_imports"
    ).status == "FAIL"


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


def test_source_identity_preserves_package_locations_across_relocation(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        for package, value in (("pkg_a", 1), ("pkg_b", 2)):
            (root / package).mkdir(parents=True)
            (root / package / "__init__.py").write_text(f"VALUE = {value}\n")

    requirements = ResidentReadinessRequirements(
        imports=("loom", "pkg_a", "pkg_b"), source_roots=("pkg_a", "pkg_b")
    )
    initial = qualified_resident_profile(_profile(first, requirements))
    relocated = qualified_resident_profile(
        _profile(
            second,
            replace(
                requirements,
                source_roots=(str(second / "pkg_b"), "./pkg_a"),
            ),
        )
    )
    assert initial.readiness_result is not None and initial.readiness_result.ok
    assert relocated.readiness_result is not None and relocated.readiness_result.ok
    assert relocated.readiness_identity == initial.readiness_identity
    assert relocated.descriptor == initial.descriptor

    (first / "pkg_a" / "__init__.py").write_text("VALUE = 2\n")
    (first / "pkg_b" / "__init__.py").write_text("VALUE = 1\n")
    swapped = qualified_resident_profile(_profile(first, requirements))
    assert swapped.readiness_result is not None and swapped.readiness_result.ok
    assert swapped.readiness_identity != initial.readiness_identity
    assert (
        swapped.descriptor.project_fingerprint != initial.descriptor.project_fingerprint
    )
    assert swapped.launch_profile.fingerprint != initial.launch_profile.fingerprint


def test_profile_probe_timeout_is_a_stable_failure(tmp_path: Path) -> None:
    sleeper = tmp_path / "sleeper"
    sleeper.write_text("#!/bin/sh\n/bin/sleep 60\n", encoding="utf-8")
    sleeper.chmod(0o700)
    profile = replace(_profile(tmp_path), python_executable=sleeper)
    result = qualify_resident_profile(profile)

    assert not result.ok
    assert result.checks[0].check_id == "python.interpreter"
    assert result.checks[0].message == "resident probe timed out"


def test_declared_flat_source_file_excludes_neighboring_project_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "stage.py"
    source.write_text("value = 1\n")
    profile = _profile(
        tmp_path, ResidentReadinessRequirements(source_roots=("stage.py",))
    )
    first = qualify_resident_profile(profile)
    assert first.ok
    (tmp_path / "README.md").write_text("operator notes\n")
    unchanged = qualify_resident_profile(profile)
    assert unchanged.identity == first.identity
    source.write_text("value = 2\n")
    changed = qualify_resident_profile(profile)
    assert changed.ok and changed.identity != first.identity


def test_local_vcs_install_origin_is_private_and_portable(tmp_path: Path) -> None:
    metadata = tmp_path / "sample-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: sample\nVersion: 1.0\n"
    )
    (tmp_path / "sample.py").write_text("value = 1\n")
    origin = metadata / "direct_url.json"
    requirement = ResidentReadinessRequirements(
        imports=("sample",), distributions=("sample",)
    )
    identities = []
    for local_path in (tmp_path / "first", tmp_path / "second"):
        origin.write_text(
            json.dumps(
                {
                    "url": local_path.as_uri(),
                    "vcs_info": {"vcs": "git", "commit_id": "a" * 40},
                }
            )
        )
        result = qualify_resident_profile(_profile(tmp_path, requirement))
        assert result.ok
        assert str(local_path) not in str(result.to_dict())
        identities.append(result.identity)
    assert identities[0] == identities[1]


def test_incompatible_python_blocks_imports_before_project_side_effects(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "imported"
    (tmp_path / "project.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8"
    )
    result = qualify_resident_profile(
        _profile(
            tmp_path,
            ResidentReadinessRequirements(imports=("project",), python_version="2.7"),
        )
    )
    assert not result.ok
    assert result.checks[0].status == "FAIL"
    assert result.checks[1].status == "SKIP"
    assert not marker.exists()


def test_installation_findings_aggregate_origin_version_and_environment_failures(
    tmp_path: Path,
) -> None:
    result = qualify_resident_profile(
        _profile(
            tmp_path,
            ResidentReadinessRequirements(
                imports=("loom",),
                distributions=("loom",),
                import_roots={"loom": "."},
                distribution_versions={"loom": "999.0"},
                required_environment=("LOOM_TEST_UNSET",),
                required_programs=("loom-test-absent-command",),
            ),
        )
    )
    failures = {check.check_id for check in result.checks if check.status == "FAIL"}
    assert failures == {"packages.required_imports", "environment.worker"}
    assert all(
        {"owner", "consequence", "repair", "applicability", "evidence"}
        <= check.details.keys()
        for check in result.checks
    )
    assert str(tmp_path) not in str(result.to_dict())


def test_required_distribution_changes_identity_but_other_package_and_lock_do_not(
    tmp_path: Path,
) -> None:
    package = tmp_path / "sample.py"
    package.write_text(
        "print('project diagnostic')\n__version__ = '1.0'\n", encoding="utf-8"
    )
    metadata = tmp_path / "sample-1.0.dist-info"
    metadata.mkdir()
    record = metadata / "METADATA"
    record.write_text(
        "Metadata-Version: 2.1\nName: sample\nVersion: 1.0\n", encoding="utf-8"
    )
    requirements = ResidentReadinessRequirements(
        imports=("sample",), distributions=("sample",), import_roots={"sample": "."}
    )
    first = qualify_resident_profile(_profile(tmp_path, requirements))
    assert first.ok
    unrelated = tmp_path / "unrelated-1.0.dist-info"
    unrelated.mkdir()
    (unrelated / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: unrelated\nVersion: 1.0\n", encoding="utf-8"
    )
    (tmp_path / "uv.lock").write_text("unrelated lock edit\n", encoding="utf-8")
    unchanged = qualify_resident_profile(_profile(tmp_path, requirements))
    assert unchanged.ok and unchanged.identity == first.identity
    record.write_text(
        "Metadata-Version: 2.1\nName: sample\nVersion: 2.0\n", encoding="utf-8"
    )
    changed = qualify_resident_profile(_profile(tmp_path, requirements))
    assert changed.ok and changed.identity != first.identity
    assert (
        changed.fingerprints["environment_fingerprint"]
        != first.fingerprints["environment_fingerprint"]
    )


def test_valid_json_from_non_python_is_not_a_python_handshake(tmp_path: Path) -> None:
    executable = tmp_path / "not-python"
    executable.write_text("#!/bin/sh\necho '{}'\n", encoding="utf-8")
    executable.chmod(0o700)
    result = qualify_resident_profile(
        replace(_profile(tmp_path), python_executable=executable)
    )
    assert not result.ok
    assert result.checks[0].check_id == "python.interpreter"
    assert result.checks[0].status == "FAIL"
