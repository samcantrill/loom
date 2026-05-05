"""Integration checks for public compose_config redaction coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from loom.config import compose_config
from loom.config.redaction import REDACTION_MARKER

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_public_compose_redacts_secret_like_key_matrix_in_artifact_payloads(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    secret_values = {
        "BASE-API-SECRET-VALUE",
        "BASE-TOKEN-SECRET-VALUE",
        "BASE-PASSWORD-SECRET-VALUE",
        "NESTED-PRIVATE-SECRET-VALUE",
        "NESTED-CREDENTIAL-SECRET-VALUE",
        "LIST-TOKEN-SECRET-VALUE",
        "OVERRIDE-PRIVATE-SECRET-VALUE",
    }
    safe_values = {
        "keep-top-note",
        "keep-nested-mode",
        "keep-list-note",
        "keep-override-label",
    }
    base.write_text(
        "name: redaction-matrix\n"
        "pipeline:\n"
        "  Api-Key: BASE-API-SECRET-VALUE\n"
        "  SECRET_token: BASE-TOKEN-SECRET-VALUE\n"
        "  Pa.s_s-Wo.rd: BASE-PASSWORD-SECRET-VALUE\n"
        "  public_note: keep-top-note\n"
        "  nested:\n"
        "    Private-Key: NESTED-PRIVATE-SECRET-VALUE\n"
        "    credential.id: NESTED-CREDENTIAL-SECRET-VALUE\n"
        "    mode: keep-nested-mode\n"
        "  items:\n"
        "    - TOKEN: LIST-TOKEN-SECRET-VALUE\n"
        "    - note: keep-list-note\n",
        encoding="utf-8",
    )

    composed = compose_config(
        base,
        overrides=(
            "+pipeline.PRIVATE-KEY=OVERRIDE-PRIVATE-SECRET-VALUE",
            "+pipeline.safe_label=keep-override-label",
        ),
    )

    resolved_pipeline = cast(dict[str, Any], composed.resolved["pipeline"])
    resolved_nested = cast(dict[str, Any], resolved_pipeline["nested"])
    resolved_items = cast(list[dict[str, Any]], resolved_pipeline["items"])
    assert resolved_pipeline["Api-Key"] == "BASE-API-SECRET-VALUE"
    assert resolved_pipeline["SECRET_token"] == "BASE-TOKEN-SECRET-VALUE"
    assert resolved_pipeline["Pa.s_s-Wo.rd"] == "BASE-PASSWORD-SECRET-VALUE"
    assert resolved_pipeline["PRIVATE-KEY"] == "OVERRIDE-PRIVATE-SECRET-VALUE"
    assert resolved_pipeline["public_note"] == "keep-top-note"
    assert resolved_nested["mode"] == "keep-nested-mode"
    assert resolved_items[1]["note"] == "keep-list-note"
    assert resolved_pipeline["safe_label"] == "keep-override-label"

    redacted_pipeline = cast(dict[str, Any], composed.redacted["pipeline"])
    redacted_nested = cast(dict[str, Any], redacted_pipeline["nested"])
    redacted_items = cast(list[dict[str, Any]], redacted_pipeline["items"])
    assert redacted_pipeline["Api-Key"] == REDACTION_MARKER
    assert redacted_pipeline["SECRET_token"] == REDACTION_MARKER
    assert redacted_pipeline["Pa.s_s-Wo.rd"] == REDACTION_MARKER
    assert redacted_pipeline["PRIVATE-KEY"] == REDACTION_MARKER
    assert redacted_nested["Private-Key"] == REDACTION_MARKER
    assert redacted_nested["credential.id"] == REDACTION_MARKER
    assert redacted_items[0]["TOKEN"] == REDACTION_MARKER
    assert redacted_pipeline["public_note"] == "keep-top-note"
    assert redacted_nested["mode"] == "keep-nested-mode"
    assert redacted_items[1]["note"] == "keep-list-note"
    assert redacted_pipeline["safe_label"] == "keep-override-label"

    provenance_payload = composed.provenance.to_dict()
    provenance_overrides = {
        override["path"]: override
        for override in cast(list[dict[str, Any]], provenance_payload["overrides"])
    }
    secret_override = provenance_overrides["pipeline.PRIVATE-KEY"]
    safe_override = provenance_overrides["pipeline.safe_label"]
    assert secret_override["raw"] == REDACTION_MARKER
    assert secret_override["value"] == REDACTION_MARKER
    assert secret_override["redacted"] is True
    assert safe_override["raw"] == "+pipeline.safe_label=keep-override-label"
    assert safe_override["value"] == "keep-override-label"
    assert safe_override["redacted"] is False

    ordinary_overrides = {
        override["path"]: override
        for override in cast(list[dict[str, Any]], composed.provenance.metadata["ordinary_overrides"])
    }
    assert ordinary_overrides["pipeline.PRIVATE-KEY"]["value"] == REDACTION_MARKER
    assert ordinary_overrides["pipeline.safe_label"]["value"] == "keep-override-label"

    artifact_payload = {
        "manifest": composed.manifest.to_dict(),
        "source_artifacts": [record.to_dict() for record in composed.source_artifacts],
        "fingerprint_records": [record.to_dict() for record in composed.fingerprint_records],
        "raw_source_snapshots": composed.raw_source_snapshots.to_dict(),
        "provenance": provenance_payload,
        "redacted": composed.redacted,
    }
    serialized_artifacts = json.dumps(artifact_payload, sort_keys=True)
    for plaintext_secret in secret_values:
        assert plaintext_secret not in serialized_artifacts
    for safe_value in safe_values:
        assert safe_value in serialized_artifacts
