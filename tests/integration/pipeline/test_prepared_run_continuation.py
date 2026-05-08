"""Integration tests for prepared-run continuation."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline.execution import (
    InsufficientPreparedStateError,
    PreparedRunContinueRequest,
    continue_prepared_run,
)
from tests.unit.loom.pipeline.execution.test_prepared_run_continue import _prepared_run


pytestmark = pytest.mark.integration


def test_prepared_run_continuation_validates_and_fails_before_user_code(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_run(tmp_path)

    with pytest.raises(InsufficientPreparedStateError):
        continue_prepared_run(
            run_store=store,
            request=PreparedRunContinueRequest(run_uri=run_uri, executor="local"),
        )
