"""Integration checks for artifact-safe config fingerprints."""

from pathlib import Path
from typing import Any, cast

import pytest

from loom.config import compose_config
from loom.config.fingerprints import ARTIFACT_SAFE_FINGERPRINT_LABEL, compare_config_artifact_fingerprints


def test_artifact_safe_fingerprint_changes_with_overlay_content(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay1 = tmp_path / "overlay.yaml"
    overlay2 = tmp_path / "overlay.yaml"

    base.write_text("name: base\npipeline:\n  value: 1\n", encoding="utf-8")
    overlay1.write_text("pipeline:\n  value: 2\n", encoding="utf-8")
    first = compose_config(base, overlays=(overlay1,))

    overlay2.write_text("pipeline:\n  value: 3\n", encoding="utf-8")
    second = compose_config(base, overlays=(overlay2,))

    assert first.fingerprint != second.fingerprint
    assert first.fingerprint_records[0].label == ARTIFACT_SAFE_FINGERPRINT_LABEL


def test_artifact_safe_fingerprint_resolves_portability_across_temp_roots(tmp_path: Path) -> None:
    def write_root(root: Path) -> tuple[Path, str]:
        root.mkdir()
        included = root / "includes"
        included.mkdir()
        include = included / "nested.yaml"
        base = root / "base.yaml"
        include.write_text("value: from-include\n", encoding="utf-8")
        base.write_text(
            "name: base\n"
            "pipeline:\n"
            "  model:\n"
            "    _include_: ./includes/nested.yaml\n"
            "  paths:\n"
            "    root: /tmp/root\n",
            encoding="utf-8",
        )
        return base, compose_config(base).fingerprint

    first_fp = write_root(tmp_path / "first")[1]
    second_fp = write_root(tmp_path / "second")[1]
    assert first_fp == second_fp


def test_artifact_safe_fingerprint_excludes_resolved_env_values_and_tracks_expressions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  root: ${oc.env:PHASE14_ROOT}\n"
        "  value: ${pipeline.root}/value\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PHASE14_ROOT", "/tmp/one")
    first = compose_config(base)
    monkeypatch.setenv("PHASE14_ROOT", "/tmp/two")
    second = compose_config(base)
    assert first.fingerprint == second.fingerprint
    first_resolver_facts = cast(list[dict[str, Any]], first.fingerprint_records[0].metadata["resolver_facts"])
    assert first_resolver_facts[0]["expression"] == "oc.env:PHASE14_ROOT"

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  root: ${oc.env:PHASE14_OTHER}\n"
        "  value: ${pipeline.root}/value\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PHASE14_OTHER", "/tmp/other")
    second_expr = compose_config(base)
    assert first.fingerprint != second_expr.fingerprint
    resolver_expression = cast(list[dict[str, Any]], second_expr.fingerprint_records[0].metadata["resolver_facts"])[0]
    assert resolver_expression["expression"] == "oc.env:PHASE14_OTHER"


def test_artifact_safe_fingerprint_redacted_secret_override_and_helper_match(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  value: one\n",
        encoding="utf-8",
    )

    with_secret = compose_config(base, overrides=("+pipeline.secret_token=top-one",))
    with_secret_other = compose_config(base, overrides=("+pipeline.secret_token=top-two",))

    assert compare_config_artifact_fingerprints(
        left=with_secret.fingerprint_records[0],
        right=with_secret_other.fingerprint_records[0],
    ).status == "match"
    ordinary_overrides = cast(
        list[dict[str, Any]],
        with_secret.fingerprint_records[0].metadata["ordinary_overrides"],
    )
    assert ordinary_overrides[0]["raw"] == "***REDACTED***"
    assert ordinary_overrides[0]["value"] == "***REDACTED***"
