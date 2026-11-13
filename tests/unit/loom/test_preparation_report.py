"""Canonical preparation composition closure at the actual write/read boundary."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from loom._preparation_report import save_composition_evidence
from loom.fingerprints import hash_mapping
from loom.pipeline.stores import LocalArtifactStore
from loom.preparation import load_preparation_report
from loom.queue.errors import QueueConflictError
from loom.serialization import stable_json_bytes


def _composition() -> dict[str, Any]:
    facts = {"null": None, "false": False, "zero": 0, "custom": {"pointer": "authored"}}
    return {
        "resolved": {"value": 41},
        "redacted": {"value": 41},
        "recipe_manifest": [],
        "manifest": {
            "schema_version": 1,
            "metadata": {"source_fact_records": facts, "specific": 1},
            "sources": [],
        },
        "provenance": {
            "schema_version": 1,
            "metadata": {
                "source_fact_records": deepcopy(facts),
                "specific": 2,
                "loom_invocation": {"argv": []},
            },
            "authorship": ["all"],
        },
    }


def _write(tmp_path: Path, *, requested=None):
    composition = _composition()
    logical = {
        "schema_version": 10,
        "composition": composition,
        "requested_composition": deepcopy(composition)
        if requested is None
        else requested,
        "project_contracts": {"unchanged": {"binding_digest": "digest"}},
    }
    store = LocalArtifactStore(tmp_path)
    companion = store.local_artifact_path(
        stage_name="prepare", name="report", codec_key="json.v1"
    ).with_suffix(".composition.json")
    primary = save_composition_evidence(logical, companion)
    ref = store.save(
        primary,
        stage_name="prepare",
        name="report",
        artifact_type="json",
        codec_key="json.v1",
    )
    return logical, store, ref, companion


def test_actual_serializer_shares_complete_equal_views_and_hydrates_all_facts(tmp_path):
    logical, store, ref, companion = _write(tmp_path)
    physical = cast(Any, store.load(ref))
    assert physical["report_format"] == "loom.preparation_report.v2"
    assert physical["schema_version"] == 10
    assert set(physical["composition"]) == {"evidence_ref"}
    saved = json.loads(companion.read_bytes())
    assert len(saved["compositions"]) == 1
    projected = saved["compositions"]["c0"]["provenance"]
    assert projected["metadata_ref"] == {
        "pointer": "/compositions/c0/manifest/metadata",
        "fields": ["source_fact_records"],
    }
    assert projected["metadata"] == {"specific": 2, "loom_invocation": {"argv": []}}
    full = cast(Any, load_preparation_report(ref, store.local_path(ref)))
    assert full == {**logical, "report_format": "loom.preparation_report.v2"}
    for name in ("composition", "requested_composition"):
        assert hash_mapping(full[name]) == hash_mapping(logical[name])
        assert stable_json_bytes(full[name]) == stable_json_bytes(logical[name])
    full["composition"]["manifest"]["metadata"]["source_fact_records"]["false"] = True
    assert stable_json_bytes(full["requested_composition"]) == stable_json_bytes(logical["requested_composition"])
    assert full["composition"]["provenance"]["metadata"]["source_fact_records"]["false"] is False
    assert (
        load_preparation_report(ref, store.local_path(ref))["composition"]
        == logical["composition"]
    )


@pytest.mark.parametrize(
    "change",
    ["resolved", "redacted", "recipes", "provenance", "manifest", "false_zero"],
)
def test_complete_distinct_views_never_share_by_selected_counts(tmp_path, change):
    requested = _composition()
    if change == "recipes":
        requested["recipe_manifest"].append({"recipe": "distinct"})
    elif change == "false_zero":
        requested["manifest"]["metadata"]["source_fact_records"]["zero"] = False
    elif change in {"resolved", "redacted"}:
        requested[change]["value"] = 42
    else:
        requested[change]["metadata"]["specific"] = 3
    logical, store, ref, companion = _write(tmp_path, requested=requested)
    assert len(json.loads(companion.read_bytes())["compositions"]) == 2
    assert load_preparation_report(ref, store.local_path(ref)) == {
        **logical,
        "report_format": "loom.preparation_report.v2",
    }


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "changed",
        "symlink",
        "outside",
        "schema",
        "pointer",
        "projection_missing",
        "projection_overlap",
        "projection_outside",
        "shared_config",
        "shared_false_zero",
        "old_format",
    ],
)
def test_damaged_actual_published_closure_refuses_complete_read(tmp_path, damage):
    _logical, store, ref, companion = _write(tmp_path)
    primary = cast(Any, store.load(ref))
    evidence = json.loads(companion.read_bytes())
    if damage == "missing":
        companion.unlink()
    elif damage == "changed":
        companion.write_bytes(companion.read_bytes() + b" ")
    elif damage == "symlink":
        outside = tmp_path / "outside.json"
        companion.rename(outside)
        companion.symlink_to(outside)
    elif damage == "old_format":
        primary.pop("report_format")
    elif damage == "outside":
        primary["composition"]["evidence_ref"]["uri"] = "../outside.json"
    elif damage == "pointer":
        primary["composition"]["evidence_ref"]["metadata"]["pointer"] = (
            "/compositions/missing"
        )
    elif damage == "shared_config":
        primary["requested_composition"]["resolved"] = {"value": 42}
    elif damage == "shared_false_zero":
        primary["composition"]["resolved"] = {"value": 0}
        primary["requested_composition"]["resolved"] = {"value": False}
    else:
        entry = evidence["compositions"]["c0"]
        if damage == "schema":
            evidence["schema"] = "loom.preparation_composition.future"
        elif damage == "projection_missing":
            entry["provenance"]["metadata_ref"]["fields"] = ["absent"]
        elif damage == "projection_overlap":
            entry["provenance"]["metadata"]["source_fact_records"] = {}
        else:
            entry["provenance"]["metadata_ref"]["pointer"] = (
                "/compositions/other/manifest/metadata"
            )
        companion.write_text(json.dumps(evidence))
        from loom.fingerprints import hash_bytes

        for name in ("composition", "requested_composition"):
            primary[name]["evidence_ref"]["checksum"] = hash_bytes(
                companion.read_bytes()
            )
    # Preserve actual primary checksum validation while isolating the damaged
    # reachable companion/reference/projection rather than unrelated byte drift.
    ref = store.save(
        primary,
        stage_name="prepare",
        name="report",
        artifact_type="json",
        codec_key="json.v1",
    )
    with pytest.raises(QueueConflictError):
        load_preparation_report(ref, store.local_path(ref))


def test_relocated_retained_closure_reads_without_original_source(tmp_path):
    logical, store, ref, companion = _write(tmp_path / "original")
    copied = tmp_path / "archive"
    copied.mkdir()
    primary = store.local_path(ref)
    (copied / primary.name).write_bytes(primary.read_bytes())
    (copied / companion.name).write_bytes(companion.read_bytes())
    primary.unlink()
    companion.unlink()
    assert load_preparation_report(ref, copied / primary.name) == {
        **logical,
        "report_format": "loom.preparation_report.v2",
    }


@pytest.mark.parametrize("version", [7, True, 12])
def test_unsupported_report_schema_refuses_before_companion_publication(tmp_path, version):
    logical, store, _ref, companion = _write(tmp_path)
    before = companion.read_bytes()
    logical["schema_version"] = version
    with pytest.raises(QueueConflictError, match="schema is unsupported"):
        save_composition_evidence(logical, companion)
    assert companion.read_bytes() == before
    # A matching primary checksum does not authorize a retired report schema.
    physical = {**logical, "report_format": "loom.preparation_report.v2"}
    retired = store.save(physical, stage_name="prepare", name="retired",
                         artifact_type="json", codec_key="json.v1")
    with pytest.raises(QueueConflictError, match="schema is unsupported"):
        load_preparation_report(retired, store.local_path(retired))


@pytest.mark.parametrize("failure", ["write", "fsync", "rename"])
def test_failed_companion_publication_preserves_existing_report_authority(
    tmp_path, monkeypatch, failure
):
    from loom.pipeline.stores import atomic
    from loom.pipeline.stores.errors import AtomicWriteError

    _logical, store, ref, companion = _write(tmp_path)
    primary = store.local_path(ref)
    original = {path: path.read_bytes() for path in (primary, companion)}

    def fail(*args, **kwargs):
        raise OSError("actual companion " + failure + " failure")

    if failure == "write":
        monkeypatch.setattr(atomic, "_write_bytes_file", fail)
    elif failure == "fsync":
        monkeypatch.setattr(atomic, "_fsync_file", fail)
    else:
        monkeypatch.setattr(atomic.os, "replace", fail)
    changed: dict[str, Any] = {"schema_version": 10, "composition": _composition()}
    changed["composition"]["resolved"]["value"] = 42
    with pytest.raises(AtomicWriteError):
        save_composition_evidence(changed, companion)
    assert {path: path.read_bytes() for path in original} == original
    assert not list(companion.parent.glob(".*.tmp.*"))
    assert cast(Any, load_preparation_report(ref, primary))["composition"][
        "resolved"
    ] == {"value": 41}


def test_native_frozen_candidate_plain_values_are_detached_before_encoding(tmp_path):
    from loom.serialization import freeze_plain_data

    logical, store, _ref, companion = _write(tmp_path)
    logical["candidate"] = freeze_plain_data(
        {"result": {"artifacts": [{"verified": True}]}}
    )
    primary = save_composition_evidence(logical, companion)
    ref = store.save(
        primary,
        stage_name="prepare",
        name="report",
        artifact_type="json",
        codec_key="json.v1",
    )
    full = cast(Any, load_preparation_report(ref, store.local_path(ref)))
    assert full["candidate"] == {"result": {"artifacts": [{"verified": True}]}}
    assert full["composition"] == logical["composition"]


def test_mapping_order_is_retained_and_order_only_changes_never_share_composition(tmp_path):
    from weave.ordered import encode_ordered_config

    requested = _composition()
    requested["resolved"] = {"z": 1, "a": {"reconstruction": {}, "detrending": {}}}
    # The two views are semantically distinct even though ordinary dict equality agrees.
    logical = {
        "schema_version": 10,
        "composition": {**requested, "resolved": dict(reversed(list(requested["resolved"].items())))},
        "requested_composition": requested,
    }
    store = LocalArtifactStore(tmp_path)
    companion = store.local_artifact_path(stage_name="prepare", name="report", codec_key="json.v1").with_suffix(".composition.json")
    primary = save_composition_evidence(logical, companion)
    ref = store.save(primary, stage_name="prepare", name="report", artifact_type="json", codec_key="json.v1")
    assert len(json.loads(companion.read_bytes())["compositions"]) == 2
    loaded = load_preparation_report(ref, store.local_path(ref))
    assert list(loaded["composition"]["resolved"]) == ["a", "z"]
    assert list(loaded["requested_composition"]["resolved"]) == ["z", "a"]
    assert list(loaded["composition"]["resolved"]["a"]) == ["reconstruction", "detrending"]
    assert encode_ordered_config(loaded["requested_composition"]["resolved"]) == encode_ordered_config(requested["resolved"])


def test_shared_ordered_views_remain_independent_after_hydration(tmp_path, monkeypatch):
    composition = _composition()
    composition["resolved"] = {
        "parts": {"reconstruction": {"values": [False, 0, 0.0, None]}, "detrending": {}},
        "branches": ["second", "first", "second"],
    }
    composition["redacted"] = deepcopy(composition["resolved"])
    monkeypatch.setattr(__import__(__name__, fromlist=["_composition"]), "_composition", lambda: deepcopy(composition))
    _, store, ref, companion = _write(tmp_path)
    assert len(json.loads(companion.read_bytes())["compositions"]) == 1
    loaded = load_preparation_report(ref, store.local_path(ref))
    for name in ("composition", "requested_composition"):
        resolved = loaded[name]["resolved"]
        assert list(resolved["parts"]) == ["reconstruction", "detrending"]
        assert resolved["branches"] == ["second", "first", "second"]
        assert [type(value) for value in resolved["parts"]["reconstruction"]["values"]] == [bool, int, float, type(None)]
    loaded["composition"]["resolved"]["parts"]["reconstruction"]["values"].append("changed")
    loaded["composition"]["resolved"]["branches"].reverse()
    assert loaded["requested_composition"] == composition
    assert loaded["composition"]["redacted"] == composition["redacted"]


def test_legacy_report_reads_original_plain_mapping_without_order_upgrade(tmp_path):
    from loom.fingerprints import hash_bytes

    logical, store, ref, companion = _write(tmp_path)
    physical = store.load(ref)
    physical["report_format"] = "loom.preparation_report.v1"
    evidence = json.loads(companion.read_bytes())
    evidence.update(schema="loom.preparation_composition.v1", schema_version=1)
    for entry in evidence["compositions"].values():
        for key in ("resolved", "redacted", "recipe_manifest"):
            entry.pop(key)
    companion.write_bytes(stable_json_bytes(evidence))
    for name in ("composition", "requested_composition"):
        for key in ("resolved", "redacted", "recipe_manifest"):
            physical[name][key] = logical[name][key]
        reference = physical[name]["evidence_ref"]
        reference["metadata"]["document_schema_version"] = 1
        reference["checksum"] = hash_bytes(companion.read_bytes())
    legacy = store.save(physical, stage_name="prepare", name="legacy-report", artifact_type="json", codec_key="json.v1")
    assert load_preparation_report(legacy, store.local_path(legacy)) == {
        **logical, "report_format": "loom.preparation_report.v1",
    }


def test_project_inspection_cannot_reorder_captured_configuration():
    from types import SimpleNamespace

    from loom.preparation import _validate_project_result

    original = {
        "resolved": {"parts": {"reconstruction": {}, "detrending": {}}},
        "redacted": {}, "recipe_manifest": [],
    }
    checked = deepcopy(original)
    checked["resolved"]["parts"] = {"detrending": {}, "reconstruction": {}}
    assert stable_json_bytes(original) == stable_json_bytes(checked)
    binding = SimpleNamespace(project_preparation={
        "target_run_uri": "file:///retained/run",
        "processor": {"schema_version": 3, "evidence_namespace": "example"},
    })
    result = {"schema_version": 3, "evidence": {"namespace": "example", "payload": {}},
              "reconciliation_key": None, "stage_contracts": {}}
    with pytest.raises(QueueConflictError, match="changed the captured composition"):
        _validate_project_result(original, checked, result, binding)
