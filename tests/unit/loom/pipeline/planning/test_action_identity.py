"""Causal key changes, independent of the current graph's presentation."""

from copy import deepcopy
from dataclasses import replace

import pytest

from loom.serialization import PlainData
from loom.pipeline import OutputSpec, StageFactorySpec, StageSpec
from loom.pipeline._project_contracts import declaration, envelope
from loom.pipeline.planning._action_identity import action_execution_identity


def _stage(name="count", source="author.text"):
    return StageSpec(
        name=name,
        factory=StageFactorySpec(target_path="project.Count"),
        stage_config={"lines": 2},
        inputs={"text": source},
        outputs={"count": OutputSpec(artifact_type="json", codec_key="json.v1")},
    )


def _contract(stage, *, digest="a" * 64):
    return envelope(
        "text-project",
        {
            "semantic_key": {"version": 1, "digest": digest},
            "payload": {"node": stage.name, "declaration": dict(stage.stage_config)},
        },
        capture="sha256:" + "c" * 64,
        node=stage.name,
        original=declaration(stage),
    )


_INSTALLATION = {
    "project": "code-1",
    "environment": "python-1",
    "executor": "image-1",
    "processor": "project:inspect",
}
_INPUTS: dict[str, dict[str, PlainData]] = {
    "text": {
        "run_uri": "file:///retained/original",
        "node": "author",
        "commit_id": "commit-1",
        "output_port": "text",
        "artifact_id": "author/text",
        "checksum": "sha256:" + "d" * 64,
        "closure_digest": "sha256:" + "e" * 64,
    }
}


def test_alias_and_edge_rename_preserve_causal_identity():
    first, renamed = _stage(), _stage("count_other", "a_reused_alias.text")
    one = action_execution_identity(
        first, _contract(first), implementation=_INSTALLATION, inputs=_INPUTS
    )
    two = action_execution_identity(
        renamed, _contract(renamed), implementation=_INSTALLATION, inputs=_INPUTS
    )
    assert one == two
    assert _contract(first)["binding_digest"] != _contract(renamed)["binding_digest"]


@pytest.mark.parametrize(
    "change",
    [
        "science",
        "commit",
        "code",
        "environment",
        "executor",
        "output",
        "factory",
        "generation",
    ],
)
def test_causal_changes_invalidate_identity(change):
    stage = _stage()
    contract, installation, inputs = (
        _contract(stage),
        dict(_INSTALLATION),
        deepcopy(_INPUTS),
    )
    original = action_execution_identity(
        stage, contract, implementation=installation, inputs=inputs
    )
    generation = "default"
    if change == "science":
        contract = _contract(stage, digest="b" * 64)
    elif change == "commit":
        inputs["text"]["commit_id"] = "fresh-producer-same-bytes"
    elif change in {"code", "environment", "executor"}:
        installation["project" if change == "code" else change] = "changed"
    elif change == "output":
        stage = replace(
            stage,
            outputs={
                "count": OutputSpec(
                    artifact_type="json", codec_key="json.v1", schema_version=2
                )
            },
        )
    elif change == "factory":
        stage = replace(
            stage, factory=StageFactorySpec(target_path="project.OtherCount")
        )
    else:
        generation = "fresh-native-token"
    changed = action_execution_identity(
        stage,
        contract,
        implementation=installation,
        inputs=inputs,
        generation=generation,
    )
    assert changed != original
    assert inputs["text"]["checksum"] == _INPUTS["text"]["checksum"]


def test_unqualified_or_opted_out_actions_have_no_selectable_identity():
    stage = _stage()
    assert (
        action_execution_identity(
            stage, _contract(stage), implementation=None, inputs=_INPUTS
        )
        is None
    )
    contract = envelope(
        "text-project",
        {"semantic_key": None, "payload": None},
        capture="sha256:" + "c" * 64,
        node=stage.name,
        original=declaration(stage),
    )
    assert (
        action_execution_identity(
            stage, contract, implementation=_INSTALLATION, inputs=_INPUTS
        )
        is None
    )
    assert (
        action_execution_identity(
            stage, None, implementation=_INSTALLATION, inputs=_INPUTS
        )
        is None
    )
