"""Resident polling preserves authored semantics without widening control limits."""
import json
from pathlib import Path
from typing import Any, cast

import pytest

from loom.queue._agent_session_codec import _decode
from loom.queue._remote_stage_execution import _ResidentAssignmentBundle
from loom.queue.agent_session_transport import _read_agent_reply
from loom.queue.errors import QueueServiceError
from loom.serialization import PlainData, thaw_plain_data
from tests.unit.loom.queue.test_remote_stage_execution import _profile, _request
from tests.unit.loom.queue.test_slurm_registration_transport import _Connection


def _response(tmp_path: Path) -> dict[str, Any]:
    nested: PlainData = {"epsilon": 0.00001}
    for _ in range(11):
        nested = {"factory": nested}
    request = _request(_profile(tmp_path), stage_config={"seconds": 0.1, "model": nested},
                       input_metadata={"metric_value": 0.25})
    return {"ok": True, "result": {"result": "assignment", "request": request.to_dict()}}


def test_resident_semantics_cross_poll_reply_and_replay(tmp_path: Path) -> None:
    value = _response(tmp_path)
    connection = cast(Any, _Connection(value))
    for _ in range(2):
        reply = _read_agent_reply(connection, "poll", b"{}", "agent")
        request = _ResidentAssignmentBundle.from_dict(thaw_plain_data(reply["request"]))
        assert request.to_dict() == value["result"]["request"]
    assert connection.paths == ["/v1/agent/poll"] * 2


@pytest.mark.parametrize("field", ["attempt", "size_bytes", "control_value"])
def test_resident_semantics_do_not_widen_control_scalars(tmp_path: Path, field: str) -> None:
    value = _response(tmp_path)
    request = value["result"]["request"]
    owner = request["inputs"][0] if field == "size_bytes" else request if field == "attempt" else value
    owner[field] = 0.5
    with pytest.raises(QueueServiceError, match="JSON value is invalid"):
        _decode(json.dumps(value).encode())


@pytest.mark.parametrize("invalid", ["nonfinite", "depth", "collection", "body", "schema"])
def test_resident_semantic_and_body_bounds_remain_finite(tmp_path: Path, invalid: str) -> None:
    value = _response(tmp_path)
    request = value["result"]["request"]
    if invalid == "nonfinite":
        request["worker_metadata"]["metric"] = float("nan")
    elif invalid == "depth":
        nested: object = 0
        for _ in range(65):
            nested = {"nested": nested}
        request["resolved_runtime"] = nested
    elif invalid == "collection":
        request["worker_metadata"]["values"] = list(range(65))
    elif invalid == "body":
        request["worker_metadata"]["large"] = "x" * 65536
    else:
        request["schema_version"] = 99
    with pytest.raises(QueueServiceError):
        _decode(json.dumps(value).encode())
