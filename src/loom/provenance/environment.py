"""Environment provenance capture."""

from __future__ import annotations

import getpass
import os
import platform
import sys

from loom.timestamps import utc_timestamp

from .errors import ProvenanceRedactionError
from .models import EnvironmentProvenance

_SECRET_HINTS = (
    "token",
    "secret",
    "password",
    "api_key",
    "credential",
    "private_key",
)


def _redact(value: str, key: str) -> str:
    lower = key.lower()
    if any(token in lower for token in _SECRET_HINTS):
        return "redacted"
    return value


def capture_environment_provenance(
    env_keys: tuple[str, ...] = (),
    *,
    include_user: bool = False,
) -> EnvironmentProvenance:
    selected_env: dict[str, str] = {}
    for key in env_keys:
        value = os.environ.get(key)
        if value is None:
            continue
        selected_env[key] = _redact(value, key)

    user = None
    if include_user:
        try:
            user = getpass.getuser()
        except (OSError, KeyError) as exc:
            raise ProvenanceRedactionError("Unable to capture username") from exc

    return EnvironmentProvenance(
        python_version=platform.python_version(),
        python_executable=sys.executable,
        platform=platform.platform(),
        machine=platform.machine(),
        processor=platform.processor() or None,
        hostname=platform.node(),
        user=user,
        selected_env=selected_env,
        container={},
        metadata={"captured_with": utc_timestamp()},
    )
