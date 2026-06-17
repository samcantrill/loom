"""Integration coverage for public argv config helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from weave import RecipeCatalog, compose_config_from_argv
from weave.api import ConfigArgvCompositionResult, ConfigArgvInspectionResult, inspect_config_from_argv
from weave.errors import ConfigLoadError, ConfigMergeError, ConfigValidationError
from weave.plain import PlainData


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _mapping(value: object) -> dict[str, PlainData]:
    assert isinstance(value, dict)
    return cast(dict[str, PlainData], value)


def _source_artifact_payloads(result: ConfigArgvCompositionResult) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], record.to_dict()) for record in result.composed_config.source_artifacts]


def test_compose_config_from_argv_returns_result_records_and_composes_scoped_overlays(tmp_path: Path) -> None:
    base = _write(
        tmp_path / "configs" / "base.yaml",
        "data:\n  keyA: baseA\n  keyB: baseB\nmodel:\n  name: base\n  keep: true\n",
    )
    _write(tmp_path / "configs" / "data" / "data_A.yaml", "keyB: overlayB\nkeyC: overlayC\n")
    _write(tmp_path / "configs" / "model" / "model_B.yaml", "_replace_: true\nname: overlay\n")
    _write(tmp_path / "configs" / "runtime_local.yaml", "kind: local\n")

    result = compose_config_from_argv(
        [
            "run",
            str(base),
            "data/=data_A",
            "model/=model_B",
            "+runtime/=runtime_local",
            "+data.keyD=final",
            "--dry-run",
        ],
        command_choices={"run"},
        allow_unparsed=True,
    )

    assert isinstance(result, ConfigArgvCompositionResult)
    assert result.command == "run"
    assert result.base_config_path == str(base)
    assert result.value_overrides == result.parsed_argv.value_overrides
    assert result.scoped_overlays == result.parsed_argv.scoped_overlays
    assert result.unparsed_args == result.parsed_argv.unparsed_args
    assert result.unparsed_args[0].raw == "--dry-run"
    assert result.warnings == ()

    data = _mapping(result.composed_config.resolved["data"])
    assert data == {"keyA": "baseA", "keyB": "overlayB", "keyC": "overlayC", "keyD": "final"}
    assert _mapping(result.composed_config.resolved["model"]) == {"name": "overlay"}
    assert _mapping(result.composed_config.resolved["runtime"]) == {"kind": "local"}

    scoped_artifacts = [
        artifact for artifact in _source_artifact_payloads(result)
        if cast(dict[str, Any], artifact["metadata"]).get("role") == "argv_scoped_overlay"
    ]
    assert len(scoped_artifacts) == 3
    metadata = cast(dict[str, Any], result.composed_config.provenance.metadata)
    assert metadata["argv_scoped_overlay_count"] == 3

    payload = result.to_dict()
    assert payload["command"] == "run"
    assert cast(dict[str, Any], payload["parsed_argv"])["unparsed_args"] == [{"raw": "--dry-run", "order": 6}]
    assert cast(dict[str, Any], payload["composed_config"])["resolved"] == result.composed_config.resolved


def test_compose_config_from_argv_defaults_to_sys_argv_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _write(tmp_path / "configs" / "base.yaml", "data:\n  value: base\n")
    monkeypatch.setattr("sys.argv", ["project-cli", "run", str(base), "data.value=from-sys-argv"])

    result = compose_config_from_argv(command_choices={"run"})

    assert result.command == "run"
    assert result.base_config_path == str(base)
    assert result.composed_config.resolved["data"] == {"value": "from-sys-argv"}


def test_inspect_config_from_argv_exposes_argv_stage_even_without_overlays(tmp_path: Path) -> None:
    base = _write(tmp_path / "configs" / "base.yaml", "data:\n  value: base\n")

    result = inspect_config_from_argv(["inspect", str(base)], command_choices={"inspect"})

    assert isinstance(result, ConfigArgvInspectionResult)
    stage_names = tuple(stage.name for stage in result.inspection.stages)
    stage = result.inspection.stage("argv_scoped_overlays")
    assert stage is not None
    assert stage.payload == {"scoped_overlay_count": 0, "scoped_overlays": []}
    assert stage_names.index("argv_scoped_overlays") == stage_names.index("file_include_expansion") + 1
    assert result.to_composed_config().resolved == result.inspection.resolved


def test_compose_config_from_argv_warnings_are_helper_local_and_artifact_free(tmp_path: Path) -> None:
    base = _write(tmp_path / "configs" / "base.yaml", "model:\n  name: base\noutput_dir: results/model_B.yaml\n")
    _write(tmp_path / "configs" / "model" / "model_B.yaml", "name: overlay\n")

    result = compose_config_from_argv(["run", str(base), "model=model_B", "output_dir=results/model_B.yaml"])

    assert result.composed_config.resolved["model"] == "model_B"
    assert result.composed_config.resolved["output_dir"] == "results/model_B.yaml"
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.code == "possible_missing_scoped_overlay_slash"
    assert warning.source_order == 2
    assert warning.token == "model=model_B"
    assert warning.path == "model"
    assert cast(str, warning.details["rhs"]) == "model_B"
    assert warning.to_dict()["details"] == warning.details

    artifact_payload = json.dumps(
        {
            "manifest": result.composed_config.manifest.to_dict(),
            "provenance": result.composed_config.provenance.to_dict(),
            "source_artifacts": [record.to_dict() for record in result.composed_config.source_artifacts],
            "fingerprint_records": [record.to_dict() for record in result.composed_config.fingerprint_records],
            "raw_source_snapshots": result.composed_config.raw_source_snapshots.to_dict(),
        },
        sort_keys=True,
    )
    assert "possible_missing_scoped_overlay_slash" not in artifact_payload


def test_compose_config_from_argv_preserves_raw_snapshot_opt_in_for_scoped_overlays(tmp_path: Path) -> None:
    base = _write(tmp_path / "configs" / "base.yaml", "data:\n  value: base\n")
    overlay = _write(tmp_path / "configs" / "data" / "data_A.yaml", "value: overlay\n")

    result = compose_config_from_argv(
        ["run", str(base), "data/=data_A"],
        include_raw_source_snapshots=True,
    )

    references = [reference.to_dict() for reference in result.composed_config.raw_source_snapshots.references]
    scoped_reference = next(reference for reference in references if reference["path"] == str(overlay.resolve()))
    assert scoped_reference["kind"] == "overlay"
    assert scoped_reference["availability"] == "available"
    payload_id = cast(str, scoped_reference["payload_id"])
    payloads = {payload.payload_id: payload for payload in result.composed_config.raw_source_snapshots.payloads}
    assert payloads[payload_id].content == "value: overlay\n"


def test_compose_config_from_argv_applies_scoped_overlays_before_recipes_and_overrides_after(tmp_path: Path) -> None:
    def echo_recipe(value: str) -> dict[str, str]:
        return {"resolved": value}

    catalog = RecipeCatalog()
    catalog.register("echo", echo_recipe)
    base = _write(tmp_path / "configs" / "base.yaml", "pipeline:\n  _recipe_: echo\n  value: base\n")
    _write(tmp_path / "configs" / "pipeline" / "pipeline_A.yaml", "value: overlay\n")

    result = compose_config_from_argv(
        ["run", str(base), "pipeline/=pipeline_A", "pipeline.resolved=final"],
        recipe_catalog=catalog,
    )

    assert result.composed_config.resolved["pipeline"] == {"resolved": "final"}


def test_compose_config_from_argv_structured_errors(tmp_path: Path) -> None:
    base = _write(tmp_path / "configs" / "base.yaml", "data:\n  value: base\nleaf: value\n")
    _write(tmp_path / "configs" / "data" / "bad.yaml", "- not\n- mapping\n")
    _write(tmp_path / "configs" / "leaf" / "child" / "overlay.yaml", "value: overlay\n")

    with pytest.raises(ConfigValidationError) as unknown:
        compose_config_from_argv(["serve", str(base)], command_choices={"run"})
    assert unknown.value.context is not None
    assert unknown.value.context.code == "unknown_command"
    assert unknown.value.context.source_kind == "argv"

    with pytest.raises(ConfigValidationError) as missing:
        compose_config_from_argv(["run", str(base), "missing/=overlay"])
    assert missing.value.context is not None
    assert missing.value.context.code == "missing_scoped_overlay_source"
    assert missing.value.context.details is not None
    assert "candidate_paths" in missing.value.context.details

    with pytest.raises(ConfigLoadError) as bad_source:
        compose_config_from_argv(["run", str(base), "data/=bad"])
    assert bad_source.value.context is not None
    assert bad_source.value.context.code == "scoped_overlay_root_not_mapping"
    assert bad_source.value.context.source_kind == "argv_scoped_overlay"

    with pytest.raises(ConfigMergeError) as bad_target:
        compose_config_from_argv(["run", str(base), "+leaf/child/=overlay"])
    assert bad_target.value.context is not None
    assert bad_target.value.context.code == "non_mapping_scoped_overlay_parent"
