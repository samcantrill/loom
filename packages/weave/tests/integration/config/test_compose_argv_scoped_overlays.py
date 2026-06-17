"""Integration coverage for private argv scoped overlay composition."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from weave import RecipeCatalog
from weave._argv import parse_config_argv
from weave.compose import _inspect_config_composition_with_argv_scoped_overlays
from weave.errors import ConfigLoadError, ConfigMergeError
from weave.plain import PlainData


def _mapping(value: object) -> dict[str, PlainData]:
    assert isinstance(value, dict)
    return cast(dict[str, PlainData], value)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _inspect_from_argv(
    argv: list[str],
    *,
    recipe_catalog: RecipeCatalog | None = None,
    include_raw_source_snapshots: bool = False,
):
    parsed = parse_config_argv(argv, command_choices={"run"})
    return _inspect_config_composition_with_argv_scoped_overlays(
        parsed.base_config_path,
        recipe_catalog=recipe_catalog or RecipeCatalog(),
        argv_scoped_overlays=parsed.scoped_overlays,
        overrides=parsed.override_strings,
        include_raw_source_snapshots=include_raw_source_snapshots,
    )


def _authorship_by_path(inspection) -> dict[str, dict[str, Any]]:
    metadata = cast(dict[str, Any], inspection.provenance.metadata)
    source_facts = cast(dict[str, Any], metadata["source_fact_records"])
    records = cast(list[dict[str, Any]], source_facts["final_value_authorship"])
    return {cast(str, record["config_path"]): record for record in records}


def _scoped_source_artifacts(inspection) -> list[dict[str, Any]]:
    artifacts = []
    for artifact in inspection.source_artifacts:
        payload = cast(dict[str, Any], artifact.to_dict())
        metadata = cast(dict[str, Any], payload["metadata"])
        if metadata.get("role") == "argv_scoped_overlay":
            artifacts.append(payload)
    return artifacts


def test_private_scoped_overlay_merges_with_authorship_and_artifacts(tmp_path: Path) -> None:
    base = _write(
        tmp_path / "configs" / "base.yaml",
        "data:\n  keyA: baseA\n  keyB: baseB\n",
    )
    scoped = _write(
        tmp_path / "configs" / "data" / "data_A.yaml",
        "keyB: overlayB\nkeyC: overlayC\n",
    )

    inspection = _inspect_from_argv(["run", str(base), "data/=data_A"])

    data = _mapping(inspection.resolved["data"])
    assert data == {"keyA": "baseA", "keyB": "overlayB", "keyC": "overlayC"}
    assert inspection.stage("argv_scoped_overlays") is not None
    stage_names = tuple(stage.name for stage in inspection.stages)
    assert stage_names.index("argv_scoped_overlays") == stage_names.index("file_include_expansion") + 1

    artifacts = _scoped_source_artifacts(inspection)
    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "overlay"
    assert artifacts[0]["path"] == str(scoped.resolve())
    scoped_metadata = cast(dict[str, Any], cast(dict[str, Any], artifacts[0]["metadata"])["argv_scoped_overlay"])
    assert scoped_metadata["raw"] == "data/=data_A"
    assert scoped_metadata["scope_path"] == ["data"]
    assert scoped_metadata["operation"] == "update"
    assert scoped_metadata["insertion_stage"] == "argv_scoped_overlays"

    authorship = _authorship_by_path(inspection)
    assert authorship["$.data.keyB"]["source_kind"] == "argv_scoped_overlay"
    assert authorship["$.data.keyB"]["composition_stage"] == "argv_scoped_overlays"
    assert authorship["$.data.keyA"]["source_kind"] == "base"

    fingerprint_metadata = cast(dict[str, Any], inspection.fingerprint_records[0].metadata)
    source_facts = cast(list[dict[str, Any]], fingerprint_metadata["source_artifact_facts"])
    scoped_facts = [fact for fact in source_facts if fact.get("role") == "argv_scoped_overlay"]
    assert len(scoped_facts) == 1
    assert list(cast(dict[str, Any], scoped_facts[0]["argv_scoped_overlay"])["scope_path"]) == ["data"]


def test_private_scoped_overlay_supports_nested_add_base_fallback_and_replace(tmp_path: Path) -> None:
    base = _write(
        tmp_path / "configs" / "base.yaml",
        "model:\n  name: base\n  keep: yes\n",
    )
    _write(tmp_path / "configs" / "pipeline_A.yaml", "kind: local\n")
    _write(tmp_path / "configs" / "model" / "model_B.yaml", "_replace_: true\nname: overlay\n")

    inspection = _inspect_from_argv(
        [
            "run",
            str(base),
            "+runtime/=pipeline_A",
            "model/=model_B",
        ],
    )

    assert _mapping(inspection.resolved["runtime"]) == {"kind": "local"}
    model = _mapping(inspection.resolved["model"])
    assert model == {"name": "overlay"}
    authorship = _authorship_by_path(inspection)
    assert authorship["$.runtime.kind"]["composition_stage"] == "argv_scoped_overlays"
    assert authorship["$.model.name"]["composition_stage"] == "argv_scoped_overlays"


def test_private_scoped_overlay_applies_before_recipes_and_value_overrides_win(tmp_path: Path) -> None:
    def echo_recipe(value: str) -> dict[str, str]:
        return {"resolved": value}

    catalog = RecipeCatalog()
    catalog.register("echo", echo_recipe)
    base = _write(
        tmp_path / "configs" / "base.yaml",
        "pipeline:\n  _recipe_: echo\n  value: base\n",
    )
    _write(tmp_path / "configs" / "pipeline" / "pipeline_A.yaml", "value: overlay\n")

    inspection = _inspect_from_argv(
        ["run", str(base), "pipeline/=pipeline_A", "pipeline.resolved=final"],
        recipe_catalog=catalog,
    )

    assert inspection.resolved["pipeline"] == {"resolved": "final"}
    stage_names = tuple(stage.name for stage in inspection.stages)
    assert stage_names.index("argv_scoped_overlays") < stage_names.index("recipe_argument_interpolation")
    assert stage_names.index("ordinary_overrides") > stage_names.index("recipe_expansion")


def test_private_scoped_overlay_raw_snapshot_opt_in_captures_overlay_source(tmp_path: Path) -> None:
    base = _write(tmp_path / "configs" / "base.yaml", "data:\n  value: base\n")
    overlay = _write(tmp_path / "configs" / "data" / "data_A.yaml", "value: overlay\n")

    inspection = _inspect_from_argv(
        ["run", str(base), "data/=data_A"],
        include_raw_source_snapshots=True,
    )

    references = [reference.to_dict() for reference in inspection.raw_source_snapshots.references]
    scoped_reference = next(reference for reference in references if reference["path"] == str(overlay.resolve()))
    assert scoped_reference["kind"] == "overlay"
    assert scoped_reference["availability"] == "available"
    payload_id = scoped_reference["payload_id"]
    payloads = {payload.payload_id: payload for payload in inspection.raw_source_snapshots.payloads}
    assert payload_id in payloads
    assert payloads[cast(str, payload_id)].content == "value: overlay\n"


def test_private_scoped_overlay_reports_structured_target_errors(tmp_path: Path) -> None:
    base = _write(tmp_path / "configs" / "base.yaml", "existing:\n  value: true\nleaf: value\n")
    _write(tmp_path / "configs" / "missing" / "overlay.yaml", "value: overlay\n")
    _write(tmp_path / "configs" / "existing" / "overlay.yaml", "value: overlay\n")
    _write(tmp_path / "configs" / "leaf" / "overlay.yaml", "value: overlay\n")
    _write(tmp_path / "configs" / "leaf" / "child" / "overlay.yaml", "value: overlay\n")

    with pytest.raises(ConfigMergeError) as missing_exc:
        _inspect_from_argv(["run", str(base), "missing/=overlay"])
    assert missing_exc.value.context is not None
    assert missing_exc.value.context.code == "missing_scoped_overlay_target"
    assert missing_exc.value.context.source_kind == "argv_scoped_overlay"
    assert missing_exc.value.context.details is not None
    assert missing_exc.value.context.details["raw"] == "missing/=overlay"

    with pytest.raises(ConfigMergeError) as existing_exc:
        _inspect_from_argv(["run", str(base), "+existing/=overlay"])
    assert existing_exc.value.context is not None
    assert existing_exc.value.context.code == "existing_scoped_overlay_target"

    with pytest.raises(ConfigMergeError) as parent_exc:
        _inspect_from_argv(["run", str(base), "+leaf/child/=overlay"])
    assert parent_exc.value.context is not None
    assert parent_exc.value.context.code == "non_mapping_scoped_overlay_parent"


def test_private_scoped_overlay_wraps_non_mapping_source_with_context(tmp_path: Path) -> None:
    base = _write(tmp_path / "configs" / "base.yaml", "data:\n  value: base\n")
    _write(tmp_path / "configs" / "data" / "bad.yaml", "- not\n- mapping\n")

    with pytest.raises(ConfigLoadError) as exc:
        _inspect_from_argv(["run", str(base), "data/=bad"])

    context = exc.value.context
    assert context is not None
    assert context.code == "scoped_overlay_root_not_mapping"
    assert context.source_kind == "argv_scoped_overlay"
    assert context.directive == "argv_scoped_overlay"
    assert context.details is not None
    assert context.details["raw"] == "data/=bad"
