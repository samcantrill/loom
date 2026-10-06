"""Bounded agent wire decoding and indeterminate transport outcomes."""
from __future__ import annotations

from collections.abc import Mapping

import json

import math

from loom.serialization import is_plain_data

from .agent_sessions import (
    AgentOffer,
    AgentProviderReleaseProof,
    AgentRegistration,
    AgentRetirementProof,
)

from .errors import QueueServiceError

_MAX_BODY_BYTES = 65_536

_MAX_QUERY_RESPONSE_BYTES = 1_048_576

_MAX_JSON_DEPTH = 8

_MAX_JSON_COLLECTION = 64

_MAX_FAILURE_JSON_DEPTH = 512

_MAX_FAILURE_JSON_COLLECTION = 256


class _IndeterminateAgentProtocolError(QueueServiceError):
    """The request may have mutated its durable owner before transport failed."""


def _registration(value: Mapping[str, object]) -> AgentRegistration:
    _exact(
        value,
        {
            "idempotency_key",
            "coordinator_id",
            "coordinator_epoch",
            "agent_root_id",
            "config_revision",
            "inventory_revision",
            "availability_revision",
            "declared_pools",
            "declared_capabilities",
            "session_id",
            "retirement_verifier",
        },
    )
    capabilities = value["declared_capabilities"]
    pools = value["declared_pools"]
    if (
        not isinstance(capabilities, list)
        or any(not isinstance(item, str) for item in capabilities)
        or not isinstance(pools, list)
        or any(not isinstance(item, str) for item in pools)
    ):
        raise QueueServiceError("agent registration scope is invalid")
    session_id = value["session_id"]
    if session_id is not None and not isinstance(session_id, str):
        raise QueueServiceError("agent session ID is invalid")
    return AgentRegistration(
        idempotency_key=_string(value, "idempotency_key"),
        coordinator_id=_string(value, "coordinator_id"),
        coordinator_epoch=_string(value, "coordinator_epoch"),
        agent_root_id=_string(value, "agent_root_id"),
        config_revision=_string(value, "config_revision"),
        inventory_revision=_string(value, "inventory_revision"),
        availability_revision=_string(value, "availability_revision"),
        declared_pools=tuple(pools),
        declared_capabilities=tuple(capabilities),
        session_id=session_id,
        retirement_verifier=(
            _string(value, "retirement_verifier")
            if value["retirement_verifier"] is not None
            else None
        ),
    )


def _offer(value: Mapping[str, object]) -> AgentOffer:
    try:
        return AgentOffer.from_value(value)
    except Exception as exc:
        if isinstance(exc, QueueServiceError):
            raise
        raise QueueServiceError("agent offer is invalid") from exc


def _exact_integer_quantity(value: object, name: str) -> int:
    if not isinstance(value, Mapping):
        raise QueueServiceError(f"agent capacity atom {name} is invalid")
    _exact(value, {"numerator", "denominator"})
    numerator = _integer(value, "numerator")
    denominator = _integer(value, "denominator")
    if denominator != 1:
        raise QueueServiceError(f"agent capacity atom {name} must be integral")
    return numerator


def _retirement_proof(value: Mapping[str, object]) -> AgentRetirementProof:
    _exact(
        value,
        {
            "session_id",
            "coordinator_id",
            "coordinator_epoch",
            "agent_id",
            "agent_root_id",
            "policy_revision",
            "config_revision",
            "inventory_revision",
            "availability_revision",
            "reference_revision",
            "reference_digest",
            "retirement_secret",
        },
    )
    return AgentRetirementProof(
        session_id=_string(value, "session_id"),
        coordinator_id=_string(value, "coordinator_id"),
        coordinator_epoch=_string(value, "coordinator_epoch"),
        agent_id=_string(value, "agent_id"),
        agent_root_id=_string(value, "agent_root_id"),
        policy_revision=_string(value, "policy_revision"),
        config_revision=_string(value, "config_revision"),
        inventory_revision=_string(value, "inventory_revision"),
        availability_revision=_string(value, "availability_revision"),
        reference_revision=_integer(value, "reference_revision"),
        reference_digest=_string(value, "reference_digest"),
        retirement_secret=_string(value, "retirement_secret"),
    )


def _provider_release_proof(
    value: Mapping[str, object],
) -> AgentProviderReleaseProof:
    _exact(
        value,
        {
            "session_id",
            "coordinator_id",
            "coordinator_epoch",
            "agent_id",
            "agent_root_id",
            "policy_revision",
            "config_revision",
            "inventory_revision",
            "assignment_id",
            "claim_id",
            "execution_fence",
            "released_availability_revision",
            "recovery_control_operation_id",
            "retirement_secret",
        },
    )
    raw_control = value["recovery_control_operation_id"]
    if raw_control is not None and not isinstance(raw_control, str):
        raise QueueServiceError("agent recovery control proof is invalid")
    return AgentProviderReleaseProof(
        session_id=_string(value, "session_id"),
        coordinator_id=_string(value, "coordinator_id"),
        coordinator_epoch=_string(value, "coordinator_epoch"),
        agent_id=_string(value, "agent_id"),
        agent_root_id=_string(value, "agent_root_id"),
        policy_revision=_string(value, "policy_revision"),
        config_revision=_string(value, "config_revision"),
        inventory_revision=_string(value, "inventory_revision"),
        assignment_id=_string(value, "assignment_id"),
        claim_id=_string(value, "claim_id"),
        execution_fence=_string(value, "execution_fence"),
        released_availability_revision=_string(value, "released_availability_revision"),
        recovery_control_operation_id=raw_control,
        retirement_secret=_string(value, "retirement_secret"),
    )


def _string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise QueueServiceError(f"agent protocol {key} is invalid")
    return item


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise QueueServiceError(f"agent protocol {key} is invalid")
    return item


def _exact(value: Mapping[str, object], fields: set[str]) -> None:
    if set(value) != fields:
        raise QueueServiceError("agent protocol fields are invalid")


def _decode(raw: bytes, *, failure_report: bool = False) -> Mapping[str, object]:
    if len(raw) > _MAX_BODY_BYTES:
        raise QueueServiceError(
            "agent protocol body is too large (maximum 65536 bytes); "
            "reduce the report or message size"
        )
    try:
        value = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except RecursionError as exc:
        raise QueueServiceError("agent protocol JSON is too deeply nested") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QueueServiceError("agent protocol JSON is invalid") from exc
    if not isinstance(value, Mapping):
        raise QueueServiceError("agent protocol body is not an object")
    result = value.get("result")
    if isinstance(result, Mapping) and result.get("result") == "assignment":
        request = result.get("request")
        if isinstance(request, Mapping) and request.get("schema_version") == 5:
            # Shared assignments add a versioned location/scope envelope. Keep
            # their finite body budget independent of the polling response.
            _bounded_json(request, depth=0)
            _bounded_json({**value, "result": {**result, "request": None}}, depth=0)
            return value
    evidence = value.get("evidence")
    if (
        failure_report
        and isinstance(evidence, Mapping)
        and evidence.get("result_operation") == "report"
    ):
        # Validate the existing report at its existing depth budget; the extra
        # authenticated Slurm relay envelope must not narrow report-v3 support.
        _decode(
            json.dumps({"report": evidence.get("report")}).encode(), failure_report=True
        )
        _bounded_json({**value, "evidence": {**evidence, "report": None}}, depth=0)
        return value
    report = value.get("report") if failure_report else None
    if (
        isinstance(report, Mapping)
        and type(report.get("schema_version")) is int
        and report["schema_version"] in {2, 3, 4}
        and "failure" in report
    ):
        _bounded_failure_json(report["failure"])
        envelope_report = {**report, "failure": None}
        if report["schema_version"] in {3, 4} and "executor_metadata" in report:
            # Route metadata is plain data; keep its original envelope depth.
            _bounded_json(report["executor_metadata"], depth=2, plain_scalars=True)
            envelope_report["executor_metadata"] = None
        _bounded_json({**value, "report": envelope_report}, depth=0)
    else:
        _bounded_json(value, depth=0)
    return value


def _decode_run_inspection_response(raw: bytes) -> Mapping[str, object]:
    """Decode the closed status/location envelope without widening agent input."""

    if len(raw) > _MAX_QUERY_RESPONSE_BYTES:
        raise QueueServiceError("run inspection response is too large")
    try:
        value = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except RecursionError as exc:
        raise QueueServiceError("run inspection response is too deeply nested") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QueueServiceError("run inspection response JSON is invalid") from exc
    if not isinstance(value, Mapping):
        raise QueueServiceError("run inspection response is not an object")
    _bounded_json(value, depth=0, max_collection=256)
    return value


def _bounded_failure_json(value: object) -> None:
    """Validate only the declared report failure's bounded plain-data subtree."""

    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > _MAX_FAILURE_JSON_DEPTH:
            raise QueueServiceError(
                "agent report failure JSON is too deeply nested (maximum depth 512); "
                "reduce failure detail nesting"
            )
        if isinstance(item, Mapping):
            if len(item) > _MAX_FAILURE_JSON_COLLECTION:
                raise QueueServiceError(
                    "agent report failure object is too large (maximum 256 entries); "
                    "reduce failure detail collections"
                )
            if any(not isinstance(key, str) for key in item):
                raise QueueServiceError("agent report failure object key is invalid")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if len(item) > _MAX_FAILURE_JSON_COLLECTION:
                raise QueueServiceError(
                    "agent report failure collection is too large (maximum 256 items); "
                    "reduce failure detail collections"
                )
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise QueueServiceError("agent report failure JSON value is non-finite")
        elif item is not None and not isinstance(item, (str, int, bool)):
            raise QueueServiceError("agent report failure JSON value is invalid")


def _bounded_json(
    value: object, *, depth: int, max_collection: int = _MAX_JSON_COLLECTION,
    plain_scalars: bool = False,
) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise QueueServiceError("agent protocol JSON is too deeply nested")
    if isinstance(value, Mapping):
        if len(value) > max_collection:
            raise QueueServiceError("agent protocol object is too large")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 160:
                raise QueueServiceError("agent protocol object key is invalid")
            _bounded_json(item, depth=depth + 1, max_collection=max_collection,
                          plain_scalars=plain_scalars)
    elif isinstance(value, list):
        if len(value) > max_collection:
            raise QueueServiceError("agent protocol collection is too large")
        for item in value:
            _bounded_json(item, depth=depth + 1, max_collection=max_collection,
                          plain_scalars=plain_scalars)
    elif plain_scalars and is_plain_data(value):
        return
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise QueueServiceError("agent protocol JSON value is invalid")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate JSON key")
    return value


def _reject_constant(_value: str) -> object:
    raise ValueError("non-finite JSON value")
