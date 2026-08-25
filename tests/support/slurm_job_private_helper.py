"""Deterministic fake site helper for ready-stage protected-boundary tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


def main() -> int:
    request = json.loads(sys.stdin.read())
    if request.get("version") != 2:
        return 2
    action = request.get("action")
    if action == "prepare":
        expected = {
            "version",
            "action",
            "operation_id",
            "request_digest",
            "fixed_path",
            "descriptor",
        }
        if set(request) != expected or not all(
            isinstance(request[key], str) and request[key]
            for key in expected - {"version", "action"}
        ):
            return 2
        identity = request["operation_id"] + "\0" + request["request_digest"]
        secret = hashlib.sha256(("fake-site-secret\0" + identity).encode()).digest()
        path = Path(request["fixed_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, secret)
        finally:
            os.close(fd)
        print(
            json.dumps(
                {
                    "version": 2,
                    "action": "prepare",
                    "operation_id": request["operation_id"],
                    "request_digest": request["request_digest"],
                    "receipt": "fake-site-"
                    + hashlib.sha256(("receipt\0" + identity).encode()).hexdigest(),
                    "verifier": hashlib.sha256(secret).hexdigest(),
                    "expires_at": "2099-01-01T00:00:00Z",
                    "path": request["fixed_path"],
                    "descriptor": request["descriptor"],
                },
                separators=(",", ":"),
            )
        )
        return 0
    if action == "revoke":
        expected = {"version", "action", "receipt", "verifier", "path", "descriptor"}
        if set(request) != expected:
            return 2
        Path(request["path"]).unlink(missing_ok=True)
        print(
            json.dumps(
                {"version": 2, "action": "revoke", "receipt": request["receipt"]},
                separators=(",", ":"),
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
