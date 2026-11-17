"""Select the qualified test filesystem for native Fleet check downloads."""

from functools import partial
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture(autouse=True)
def _selected_fleet_download_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = os.environ.get("LOOM_TEST_LOCAL_STATE_ROOT")
    if configured is None:
        return
    root = Path(configured)
    assert root.is_absolute() and root.is_dir(), "Fleet test storage must already exist"
    from loom.fleet import self_tests

    # Native checks transfer 65 MiB companions. Use the local-state filesystem,
    # which may have a larger bound than the small artifact contract-test mount.
    monkeypatch.setattr(
        self_tests, "TemporaryDirectory", partial(TemporaryDirectory, dir=root),
    )
