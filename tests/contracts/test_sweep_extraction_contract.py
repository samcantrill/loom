"""Contract tests for unsupported extraction diagnostics."""

from __future__ import annotations

import pytest

from loom.pipeline.sweep import (
    SweepExtractionDiagnostic,
    SweepExtractionRequest,
    SweepExtractionResult,
    SweepExtractionStatus,
    SweepExtractionError,
    unsupported_extraction,
)

pytestmark = pytest.mark.contract


_REQUEST = SweepExtractionRequest(
    sweep_id="sweep-1",
    trial_id="trial-1",
    trial_index=0,
    requested_at="2020-01-01T00:00:00Z",
    run_uri="file:///runs/trial-1",
)


def test_unsupported_extraction_result_contract() -> None:
    result = unsupported_extraction(_REQUEST, message="not yet implemented")

    assert result.status is SweepExtractionStatus.UNSUPPORTED
    assert result.to_dict() == {
        "schema_version": 1,
        "request": _REQUEST.to_dict(),
        "status": SweepExtractionStatus.UNSUPPORTED.value,
        "extracted_payload": None,
        "diagnostics": [
            {
                "code": "unsupported_extraction",
                "message": "not yet implemented",
                "detail": {},
            }
        ],
        "extraction_metadata": {},
    }
    assert SweepExtractionResult.from_dict(result.to_dict()) == result


def test_extraction_rejects_malformed_payload() -> None:
    with pytest.raises(SweepExtractionError, match="must be a mapping"):
        SweepExtractionDiagnostic.from_dict({"code": "a", "message": "x", "detail": []})

    with pytest.raises(SweepExtractionError, match="must contain plain data"):
        SweepExtractionResult.from_dict(
            {
                "schema_version": 1,
                "request": _REQUEST.to_dict(),
                "status": "failed",
                "extracted_payload": {"a": object()},
                "diagnostics": (),
                "extraction_metadata": {},
            }
        )
