"""Temporary installed-distribution fixture for Stage 28 process tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def install_stage28_entry_points(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution = root / "loom_stage28_test_plugins-1.0.dist-info"
    distribution.mkdir(parents=True)
    (distribution / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: loom-stage28-test-plugins\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (distribution / "entry_points.txt").write_text(
        """[loom.codecs]
stage28.tagged-json.v1 = tests.support.stage28_plugins:TaggedJsonCodec

[loom.resource_validators]
stage28.device = tests.support.stage28_plugins:validate_device

[loom.executors]
stage28-project = tests.support.stage28_plugins:PROJECT_EXECUTOR_REGISTRATION
stage28-subprocess = tests.support.stage28_plugins:PROJECT_SUBPROCESS_EXECUTOR_REGISTRATION
""",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(root))
    existing = os.environ.get("PYTHONPATH")
    repository_root = Path(__file__).resolve().parents[2]
    entries = [str(root), str(repository_root)]
    if existing:
        entries.append(existing)
    python_path = os.pathsep.join(entries)
    monkeypatch.setenv("PYTHONPATH", python_path)


__all__ = ["install_stage28_entry_points"]
