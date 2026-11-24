"""Native Slurm delivery survives the authenticated registration envelope."""
from dataclasses import fields
import io
import json
from typing import Any, cast
from collections.abc import Sequence

import pytest

from loom.queue.agent_session_transport import _read_agent_reply
from loom.queue._agent_session_codec import _decode, _IndeterminateAgentProtocolError
from loom.queue.errors import QueueServiceError
from loom.queue.slurm_ready_stage import SlurmStageDelivery
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.serialization import PlainData, thaw_plain_data
from tests.unit.loom.queue.test_remote_stage_execution import _profile, _request


def _response(tmp_path, *, input_metadata=None, fingerprint_schema=2, stage_config=None):
    # A valid authored factory graph can exceed the control protocol's depth 8.
    # This follows the native request/delivery producer before HTTP serialization.
    nested: dict[str, PlainData] = {"epsilon": 0.00001}
    for _ in range(11):
        nested = {"factory": nested}
    request = _request(
        _profile(tmp_path), input_metadata=input_metadata,
        fingerprint_schema=fingerprint_schema,
        stage_config=stage_config if stage_config is not None else {
            "model": {"encoder": {"block": {"normalization": {"epsilon": 0.00001}}}},
            "data": nested,
        },
    )
    values = {field.name: getattr(request, field.name)
              for field in fields(SlurmStageDelivery)
              if field.name != "schema_version" and hasattr(request, field.name)}
    assert isinstance(request.profile, ResidentProfileDescriptor)
    delivery = SlurmStageDelivery(
        **values, profile_id="cpu",
        project_fingerprint=request.profile.project_fingerprint,
        environment_fingerprint=request.profile.environment_fingerprint,
        executor_fingerprint=request.profile.executor_fingerprint,
    )
    return {"ok": True, "result": {"assignment_id": delivery.assignment_id,
                                  "delivery": delivery.to_dict()}}


def test_ordered_delivery_exceeding_control_budget_crosses_http_and_replays(tmp_path):
    from loom.pipeline.planning.models import StageFingerprintRecord

    config = {"reconstruction": {f"item-{i}": "x" * 1100 for i in range(60)},
              "detrending": {}, "sequence": [3, 1, 3]}
    value = _response(tmp_path, fingerprint_schema=3, stage_config=config)
    assert 65536 < len(json.dumps(value).encode()) < 262144
    connection = cast(Any, _Connection(value))
    for _ in range(2):
        reply = _read_agent_reply(connection, "register", b"{}", "slurm_bootstrap")
        delivery = SlurmStageDelivery.from_dict(thaw_plain_data(reply["delivery"]))
        restored = StageFingerprintRecord.from_dict(delivery.fingerprint).payload.stage_config
        assert list(restored) == ["reconstruction", "detrending", "sequence"]
        assert list(cast(Sequence[Any], restored["sequence"])) == config["sequence"]
    for role, operation in [("agent", "register"), ("slurm_bootstrap", "handshake")]:
        with pytest.raises(_IndeterminateAgentProtocolError):
            _read_agent_reply(connection, operation, b"{}", role)


def test_retained_multi_target_retry_exceeding_one_mib_crosses_registration(tmp_path):
    from loom.pipeline.planning.models import StageFingerprintRecord

    # The retained MMPD two-target retry produced a 1,282,839-byte delivery.
    candidate = "zlib:" + "A" * 1_280_000
    stage_config = {"preparation": {"purpose": {"kind": "project", "candidate_json": candidate}}}
    value = _response(tmp_path, fingerprint_schema=3, stage_config=stage_config)
    connection = cast(Any, _Connection(value))
    assert 1_048_576 < len(connection.body) < 2_097_152
    for _ in range(2):
        response = _read_agent_reply(connection, "register", b"{}", "slurm_bootstrap")
        delivery = SlurmStageDelivery.from_dict(thaw_plain_data(response["delivery"]))
        restored = cast(Any, StageFingerprintRecord.from_dict(delivery.fingerprint).payload.stage_config)
        assert restored["preparation"]["purpose"]["candidate_json"] == candidate
    for role, operation in [("agent", "register"), ("slurm_bootstrap", "handshake")]:
        with pytest.raises(_IndeterminateAgentProtocolError):
            _read_agent_reply(connection, operation, b"{}", role)


def test_registration_reply_keeps_a_finite_transport_budget(tmp_path):
    # An otherwise valid delivery that exceeds the registration byte budget.
    value = _response(tmp_path, fingerprint_schema=3,
                      stage_config={"content": "x" * (8 * 1024 * 1024)})
    connection = cast(Any, _Connection(value))
    with pytest.raises(QueueServiceError, match="body is too large"):
        _decode(connection.body, slurm_registration=True)
    with pytest.raises(_IndeterminateAgentProtocolError):
        _read_agent_reply(connection, "register", b"{}", "slurm_bootstrap")


def test_large_unknown_registration_is_not_treated_as_a_delivery(tmp_path):
    value = _response(tmp_path, fingerprint_schema=3, stage_config={"content": "x" * 70000})
    value["result"]["delivery"]["schema_version"] = 99
    with pytest.raises(QueueServiceError, match="body is too large"):
        _decode(json.dumps(value).encode(), slurm_registration=True)


class _Response(io.BytesIO):
    status = 200


class _Connection:
    def __init__(self, value):
        self.body = json.dumps(value).encode()
        self.paths = []

    def request(self, _method, path, **_kwargs):
        self.paths.append(path)

    def getresponse(self):
        return _Response(self.body)


def test_native_delivery_crosses_registration_reply_and_replay(tmp_path):
    value = _response(tmp_path)
    with pytest.raises(QueueServiceError):
        _decode(json.dumps(value).encode())
    connection = cast(Any, _Connection(value))
    first = _read_agent_reply(connection, "register", b"{}", "slurm_bootstrap")
    replay = _read_agent_reply(connection, "register", b"{}", "slurm_bootstrap")
    assert thaw_plain_data(first) == thaw_plain_data(replay) == value["result"]
    delivery = SlurmStageDelivery.from_dict(thaw_plain_data(first["delivery"]))
    assert cast(dict[str, Any], delivery.fingerprint)["payload"]["stage_config"]["model"]["encoder"]["block"]["normalization"]["epsilon"] == 0.00001
    assert thaw_plain_data(delivery.fingerprint) == value["result"]["delivery"]["fingerprint"]
    assert connection.paths == ["/v1/slurm_bootstrap/register"] * 2
    for role, operation in [("agent", "register"), ("slurm_bootstrap", "handshake")]:
        with pytest.raises(_IndeterminateAgentProtocolError):
            _read_agent_reply(connection, operation, b"{}", role)


def test_input_artifact_metadata_crosses_registration_reply_and_replay(tmp_path):
    metadata = {"metric_value": 0.9882636666297913,
                "observations": [None, True, 2, 0.25, "ready", {"ratio": 0.75}]}
    value = _response(tmp_path, input_metadata=metadata)
    connection = cast(Any, _Connection(value))
    first = _read_agent_reply(connection, "register", b"{}", "slurm_bootstrap")
    replay = _read_agent_reply(connection, "register", b"{}", "slurm_bootstrap")
    assert thaw_plain_data(first) == thaw_plain_data(replay) == value["result"]
    delivery = SlurmStageDelivery.from_dict(thaw_plain_data(first["delivery"]))
    assert thaw_plain_data(delivery.inputs[0].metadata) == metadata
    assert delivery.to_dict() == value["result"]["delivery"]


def test_input_metadata_does_not_widen_descriptor_or_wire_limits(tmp_path):
    value = _response(tmp_path)
    descriptor = value["result"]["delivery"]["inputs"][0]
    descriptor["size_bytes"] = 1.5
    with pytest.raises(QueueServiceError, match="JSON value is invalid"):
        _decode(json.dumps(value).encode(), slurm_registration=True)
    descriptor["size_bytes"] = 5
    for metadata, message in [
        ({"metric_value": float("nan")}, "JSON is invalid"),
        ({"values": list(range(65))}, "collection is too large"),
    ]:
        descriptor["metadata"] = metadata
        with pytest.raises(QueueServiceError, match=message):
            _decode(json.dumps(value).encode(), slurm_registration=True)
    nested = 1
    for _ in range(6):
        nested = {"nested": nested}
    descriptor["metadata"] = nested
    with pytest.raises(QueueServiceError, match="deeply nested"):
        _decode(json.dumps(value).encode(), slurm_registration=True)


def test_registration_keeps_control_and_semantic_limits(tmp_path):
    value = _response(tmp_path)
    assert _decode(json.dumps(value).encode(), slurm_registration=True) == value
    for field in ("unexpected", "delivery"):
        nested = 1
        for _ in range(65 if field == "delivery" else 9):
            nested = {"nested": nested}
        changed = json.loads(json.dumps(value))
        if field == "delivery":
            changed["result"]["delivery"]["fingerprint"]["payload"]["stage_config"] = nested
        else:
            changed[field] = nested
        with pytest.raises(QueueServiceError, match="deeply nested"):
            _decode(json.dumps(changed).encode(), slurm_registration=True)
    value["result"]["delivery"]["worker_metadata"]["metric_values"] = list(range(65))
    with pytest.raises(QueueServiceError, match="collection is too large"):
        _decode(json.dumps(value).encode(), slurm_registration=True)


def test_registration_keeps_body_and_scalar_limits(tmp_path):
    value = _response(tmp_path)
    value["extra"] = "x" * 65536
    with pytest.raises(QueueServiceError, match="body is too large"):
        _decode(json.dumps(value).encode(), slurm_registration=True)
    del value["extra"]
    value["result"]["delivery"]["attempt"] = 1.5
    with pytest.raises(QueueServiceError, match="JSON value is invalid"):
        _decode(json.dumps(value).encode(), slurm_registration=True)
    with pytest.raises(QueueServiceError, match="JSON is invalid"):
        _decode(b'{"ok":true,"ok":false}', slurm_registration=True)


@pytest.mark.parametrize("schema", [True, 4, 99])
def test_registration_does_not_extend_unknown_delivery_schemas(tmp_path, schema):
    value = _response(tmp_path)
    value["result"]["delivery"]["schema_version"] = schema
    with pytest.raises(QueueServiceError):
        _decode(json.dumps(value).encode(), slurm_registration=True)
