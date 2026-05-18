"""Unit tests for cleanup selectors."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from loom.pipeline.cleanup import (
    CleanupSelectionStatus,
    CleanupSelector,
    CleanupSelectorError,
    match_cleanup_candidate,
)


pytestmark = pytest.mark.unit


def _candidate() -> dict[str, object]:
    return {
        "candidate_id": "candidate-1",
        "kind": "staged_payload",
        "uri": "file:///runs/run-1/tmp/payload",
        "reason": {
            "code": "temporary_payload",
            "message": None,
            "detail": {"stage_name": "prepare", "retention_mode": "temporary"},
        },
        "recorded_at": "2020-01-01T00:00:00Z",
        "revision": {"sequence": 1, "token": "rev-1", "created_at": None},
    }


def test_cleanup_selector_round_trips_plain_data() -> None:
    selector = CleanupSelector(
        older_than_seconds=3600,
        candidate_kinds=("staged_payload",),
        reason_codes=("temporary_payload",),
        metadata_equals={"stage_name": "prepare"},
    )
    payload = selector.to_dict()

    assert payload["schema_version"] == 1
    assert payload["candidate_kinds"] == ["staged_payload"]
    assert CleanupSelector.from_dict(payload) == selector


def test_match_cleanup_candidate_explains_selected_candidate() -> None:
    selector = CleanupSelector(
        older_than_seconds=7 * 24 * 3600,
        candidate_kinds=("staged_payload",),
        reason_codes=("temporary_payload",),
        retention_modes=("temporary",),
        stage_names=("prepare",),
    )
    selection = match_cleanup_candidate(
        _candidate(),
        selector,
        now=datetime(2020, 1, 10, tzinfo=timezone.utc),
    )

    assert selection.status is CleanupSelectionStatus.SELECTED
    assert selection.selected is True
    assert {explanation.field for explanation in selection.explanations} == {
        "older_than_seconds",
        "candidate_kinds",
        "reason_codes",
        "retention_modes",
        "stage_names",
    }
    assert all(explanation.matched for explanation in selection.explanations)


def test_match_cleanup_candidate_explains_skipped_candidate() -> None:
    selection = match_cleanup_candidate(
        _candidate(),
        CleanupSelector(candidate_kinds=("worker_handoff",)),
    )

    assert selection.status is CleanupSelectionStatus.SKIPPED
    assert selection.selected is False
    assert selection.explanations[0].reason_code == "candidate_kinds_mismatch"


def test_selector_rejects_expression_like_unknown_fields() -> None:
    with pytest.raises(CleanupSelectorError):
        CleanupSelector.from_dict({"schema_version": 1, "where": "kind == 'x'"})
