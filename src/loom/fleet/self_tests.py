"""Deliberate native checks with immutable intent and exact-ID continuation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import fcntl
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, cast
from uuid import uuid4

from loom.coordinator import (
    CoordinatorClient,
    CoordinatorClientError,
    CoordinatorOperatorClient,
    RunRequest,
)
from loom.deployment import load_deployment
from loom.queue.deployment import (
    _load_protected_config,
    _protected_input_path,
    load_coordinator_connection_file,
)
from loom.queue.errors import QueueConfigError
from loom.queue.models import validate_queue_id
from loom.queue.preparation import PrepareRunRequest
from loom.runs.outputs import OutputSelection
from loom.serialization import thaw_plain_data

from .configuration import _environment_files, Inventory, exclude_captures, protected_directory
from .probes import probe_configuration, verify_storage


def _publish(path: Path, value: Any) -> None:
    """Durably publish immutable intent/dispatch before any native mutation."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink()


def _read(path: Path) -> dict[str, Any]:
    _protected_input_path(path, label="self-test receipt", require_owner_only=True)
    return json.loads(path.read_text())


def _waiting(code: str, **facts: Any) -> dict[str, Any]:
    return {"outcome": "waiting", "code": code, **facts}


def verify_check(
    check: str,
    report: Mapping[str, Any],
    assignment: Mapping[str, Any],
    agent: Mapping[str, Any],
    *,
    agent_id: str,
    session_id: str,
    profile: Mapping[str, Any],
    run_uri: str,
) -> dict[str, Any]:
    """Join workload output with current native identity, settlement and capacity.

    A successful terminal row alone is insufficient. The native parent observes
    the launch UUID; the workload observes CUDA properties; provider release and
    a current offer independently establish relinquished capacity.
    """
    if (
        assignment.get("agent_id") != agent_id
        or assignment.get("session_id") != session_id
        or assignment.get("run_uri") != run_uri
        or assignment.get("stage_name") != "probe"
        or assignment.get("profile") != profile
        or not assignment.get("claim_id")
        or report.get("run_uri") != "loom-agent:" + str(assignment.get("assignment_id"))
        or report.get("stage_name") != "probe"
        or report.get("check") != check
        or report.get("synthetic") is not True
    ):
        return {"outcome": "failed", "code": "check_identity_mismatch"}
    if report.get("outcome") == "unsupported":
        return {
            "outcome": "unsupported",
            "code": "unsupported_check",
            "reason": report.get("reason"),
        }
    if report.get("outcome") != "passed":
        return {"outcome": "failed", "code": "probe_failed"}
    if check == "cpu" and report.get("result") != 49995000:
        return {"outcome": "failed", "code": "cpu_result_mismatch"}
    if check == "gpu":
        claim = assignment.get("actual_claims") or {}
        if (
            claim.get("availability") != "available"
            or claim.get("actual_gpu_uuids") is None
        ):
            return _waiting("actual_uuid_binding_unavailable")
        if (
            claim.get("assignment_id") != assignment.get("assignment_id")
            or claim.get("source") != "native_supervisor_launch"
            or claim.get("actual_gpu_uuids") != [report.get("device_uuid")]
            or report.get("device_count") != 1
            or report.get("result") != [[19.0, 22.0], [43.0, 50.0]]
        ):
            return {"outcome": "failed", "code": "gpu_uuid_or_result_mismatch"}
    proof = assignment.get("release_proof") or {}
    if (
        assignment.get("released") is not True
        or assignment.get("terminal_acknowledged") is not True
        or proof.get("assignment_id") != assignment.get("assignment_id")
        or proof.get("claim_id") != assignment.get("claim_id")
        or proof.get("session_id") != session_id
    ):
        return _waiting("waiting_for_release")
    offer = agent.get("offer") or {}
    if (
        agent.get("session_id") != session_id
        or agent.get("connected") is not True
        or offer.get("freshness") != "current"
        or assignment["claim_id"] in offer.get("reflected_claim_ids", ())
    ):
        return _waiting("fresh_offer_unavailable")
    if check == "gpu":
        keys = set(assignment["actual_claims"].get("gpu_capacity_keys", ()))
        # Native scheduling qualifies agent-local offer keys before reserving them.
        available = {
            f"{agent_id}:{atom['local_capacity_key']}"
            for atom in offer.get("gpu_atoms", ())
        }
        if not keys or not keys.issubset(available):
            return _waiting("waiting_for_capacity")
    return {"outcome": "passed", "code": "check_complete"}


def _submit_check(
    client: CoordinatorClient, directory: Path, check: str, request: RunRequest
) -> dict[str, Any] | None:
    try:
        client.start_run(request)
    except CoordinatorClientError as exc:
        if exc.mutation_outcome == "not_applied":
            _publish(directory / (check + ".rejected.json"), exc.to_dict())
            return {
                "outcome": "failed",
                "code": exc.code,
                "native_error": exc.to_dict(),
            }
        return _waiting("submission_uncertain", native_error=exc.to_dict())
    return None


def _dispatch_check(
    client: CoordinatorClient,
    directory: Path,
    intent: Mapping[str, Any],
    check: str,
) -> dict[str, Any] | None:
    request = RunRequest.from_dict(intent["requests"][check])
    identity = request.preparation.operation_id
    marker = directory / (check + ".dispatch.json")
    if not marker.exists():
        _publish(marker, {"operation_id": identity})
        submitted = _submit_check(client, directory, check, request)
        if submitted is not None:
            return submitted
    elif _read(marker) != {"operation_id": identity}:
        raise QueueConfigError("dispatch marker conflicts with immutable intent")
    rejected = directory / (check + ".rejected.json")
    if rejected.exists():
        error = _read(rejected)
        return {"outcome": "failed", "code": error["code"], "native_error": error}
    return None


def _observe_check(
    client: CoordinatorClient,
    operator: CoordinatorOperatorClient,
    directory: Path,
    intent: Mapping[str, Any],
    check: str,
    deadline: float,
) -> dict[str, Any]:
    request = RunRequest.from_dict(intent["requests"][check])
    identity = request.preparation.operation_id
    try:
        observed = client.observe_run(
            identity, timeout_seconds=max(0.001, deadline - time.monotonic())
        )
    except CoordinatorClientError as exc:
        if exc.code == "not_found":
            # The native API owns exact replay: no new ID, source or retry policy.
            return _submit_check(client, directory, check, request) or _waiting(
                "exact_request_replayed"
            )
        raise
    facts: dict[str, Any] = {"native": thaw_plain_data(observed.to_dict())}
    if (
        observed.operation is not None
        and observed.operation.state in {"failed", "cancelled", "conflict"}
        or observed.admission is not None
        and observed.admission.state.value in {"FAILED", "CANCELLED"}
    ):
        return {"outcome": "failed", "code": "native_check_failed", **facts}
    if observed.admission is None or observed.admission.state.value != "SUCCEEDED":
        return _waiting("waiting_for_capacity", **facts)
    detail = client.admission(observed.admission.admission_id)
    assignments = (
        cast(dict[str, Any], thaw_plain_data(detail.owners))
        .get("assignment", {})
        .get("assignments", [])
    )
    candidates = [
        operator.observe_assignment(row["assignment_id"]) for row in assignments
    ]
    matches = [
        row
        for row in candidates
        if row.availability == "available"
        and row.value.get("stage_name") == "probe"
        and row.value.get("terminal_acknowledged")
    ]
    if len(matches) != 1:
        return _waiting("assignment_evidence_unavailable", **facts)
    assignment = cast(dict[str, Any], thaw_plain_data(matches[0].value))
    agent_observation = operator.observe_agent(intent["agent_id"])
    facts.update(assignment=matches[0].to_dict(), agent=agent_observation.to_dict())
    selected = client.select_outputs(
        OutputSelection(
            run_uris=(observed.admission.run_uri,),
            stage_names=("probe",),
            output_name="report",
        )
    )
    if len(selected.items) != 1 or selected.next_cursor is not None:
        return _waiting("output_unavailable", **facts)
    artifact = selected.items[0].get("artifact") or {}
    if "loom.shared_publication" not in (artifact.get("metadata") or {}):
        return {"outcome": "failed", "code": "shared_publication_required", **facts}
    with tempfile.TemporaryDirectory(dir=directory) as destination:
        fetched = client.fetch_artifacts(selected.items, destination, deadline=deadline)
        row = fetched["items"][0]
        if row["outcome"] != "available":
            return {
                "outcome": "failed"
                if row["outcome"] == "integrity_failed"
                else "waiting",
                "code": "publication_" + row["outcome"],
                **facts,
            }
        path = Path(row["primary_path"])
        report = json.loads(path.read_text())
        if check == "storage":
            try:
                facts["storage"] = verify_storage(path.parent / "values.bin")
            except (OSError, ValueError):
                return {"outcome": "failed", "code": "storage_result_mismatch", **facts}
        facts["report"] = report
    result = verify_check(
        check,
        report,
        assignment,
        cast(dict[str, Any], thaw_plain_data(agent_observation.value)),
        agent_id=intent["agent_id"],
        session_id=intent["session_id"],
        profile=intent["profile"],
        run_uri=observed.admission.run_uri,
    )
    return {**result, **facts}


def self_test(
    inventory: Inventory,
    *,
    deployment: Path | None = None,
    operator_connection: Path | None = None,
    config: str = "fleet-check.yaml",
    agent_id: str | None = None,
    checks: Sequence[str] = ("cpu", "storage"),
    operation_id: str | None = None,
    retry_of: str | None = None,
    timeout_seconds: float = 120,
    env_file: Path | None = None,
    _prepare_id: str | None = None,
    _maintenance_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run selected checks or reconnect to one protected immutable check intent.

    A supplied operation ID only continues an existing receipt. New attempts use
    new IDs; retry_of links an observed failure. Deadlines detach without cancel
    or replacement. Selected requests dispatch before result observation within
    that deadline. The connection-only deployment pins native source/profile;
    the selected source must contain the base config and allow generic probes.
    """
    environments = _environment_files(inventory, env_file)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise QueueConfigError("timeout must be positive and finite")
    if (
        not checks
        or len(set(checks)) != len(checks)
        or set(checks) - {"cpu", "storage", "gpu"}
    ):
        raise QueueConfigError("checks must select cpu, storage and/or gpu")
    intent: dict[str, Any] = {}
    continuing = operation_id is not None
    operation_id = operation_id or _prepare_id or "check-" + uuid4().hex
    if _prepare_id is not None and (continuing or len(checks) != 1):
        raise QueueConfigError("maintenance preparation requires one new check slot")
    validate_queue_id(operation_id, "self-test operation ID")
    if Path(operation_id).name != operation_id or operation_id in {".", ".."}:
        raise QueueConfigError("operation ID must be a filename")
    root = inventory.path.parent / "checks"
    directory = root / operation_id
    if continuing and not (directory / "intent.json").is_file():
        raise QueueConfigError("unknown check operation; no work submitted")
    if not continuing:
        if deployment is None or operator_connection is None:
            raise QueueConfigError(
                "new checks require a connection-only deployment and operator connection"
            )
        selection = load_deployment(deployment)
        if (
            selection.connection is None
            or selection.coordinator is not None
            or selection.agent is not None
            or selection.source.mode != "shared"
        ):
            raise QueueConfigError(
                "self-tests require connection-only shared-source deployment"
            )
        connection = load_coordinator_connection_file(selection.connection)
        if connection.expected_coordinator_id is None:
            raise QueueConfigError("self-tests require a pinned coordinator identity")
        agents = [host.name for host in inventory.hosts if host.name != "coordinator"]
        if agent_id is None and len(agents) == 1:
            agent_id = agents[0]
        if agent_id not in agents:
            raise QueueConfigError("select an unambiguous inventory agent")
        _, _, role, _ = _load_protected_config(
            inventory.hosts[0].config, env_file=environments["coordinator"]
        )
        preparation = cast(Mapping[str, Any], role.get("preparation") or {})
        policy = preparation.get("profiles", {}).get(selection.preparation_profile)
        if policy is None:
            raise QueueConfigError("selected preparation profile is undeclared")
        for source in preparation.get("source_roots", {}).values():
            exclude_captures(root, [inventory.hosts[0].config.parent / source["path"]])
        operator_config = load_coordinator_connection_file(operator_connection)
        if (
            operator_config.expected_coordinator_id
            != connection.expected_coordinator_id
        ):
            raise QueueConfigError(
                "operator and workload connections must pin the same coordinator"
            )
        with CoordinatorOperatorClient.from_connection_file(
            operator_connection
        ) as operator:
            observed = operator.observe_agent(str(agent_id))
        if observed.availability != "available" or observed.freshness != "current":
            raise QueueConfigError("selected agent/profile observation is unavailable")
        agent = cast(dict[str, Any], thaw_plain_data(observed.value))
        profiles = [
            p
            for p in (agent.get("offer") or {}).get("profile_identities", ())
            if p["profile_id"] == policy["resident_profile_id"]
        ]
        if len(profiles) != 1:
            raise QueueConfigError("selected profile is unavailable or ambiguous")
        if "gpu" in checks and not (agent.get("offer") or {}).get("gpu_devices"):
            raise QueueConfigError("GPU check requires a declared GPU profile")
        requests = {}
        for check in checks:
            identity = operation_id if _prepare_id is not None else operation_id + "-" + check
            composition = probe_configuration(check, str(agent_id))
            requests[check] = RunRequest(
                PrepareRunRequest(
                    identity,
                    identity,
                    selection.source,
                    config,
                    selection.preparation_profile,
                    overrides=tuple(
                        key + "=" + json.dumps(value)
                        for key, value in composition.items()
                    ),
                ),
                identity,
            ).to_dict()
        intent = {
            "schema_version": 1,
            "operation_id": operation_id,
            "retry_of": retry_of,
            "maintenance_binding": None if _maintenance_binding is None else dict(_maintenance_binding),
            "coordinator_id": connection.expected_coordinator_id,
            "connection": str(selection.connection),
            "operator_connection": str(operator_connection.resolve()),
            "agent_id": agent_id,
            "session_id": agent["session_id"],
            "agent_root_id": agent["agent_root_id"],
            "profile": profiles[0],
            "requests": requests,
        }
        if retry_of is not None:
            if Path(retry_of).name != retry_of or retry_of in {".", ".."}:
                raise QueueConfigError("invalid predecessor operation")
            previous = _read(root / retry_of / "result.json")
            if previous["outcome"] != "failed":
                raise QueueConfigError(
                    "new attempt requires an observed failed predecessor"
                )
    protected_directory(directory)
    with (directory / "owner.lock").open("a") as lock:
        os.chmod(directory / "owner.lock", 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not continuing:
            _publish(directory / "intent.json", intent)
        intent = _read(directory / "intent.json")
        if _prepare_id is not None:
            return intent
        previous_results = (
            _read(directory / "result.json").get("checks", {})
            if (directory / "result.json").exists()
            else {}
        )
        deadline = time.monotonic() + timeout_seconds
        results: dict[str, Any] = {
            check: {"outcome": "not_requested"} for check in ("cpu", "storage", "gpu")
        }
        with (
            CoordinatorClient.from_connection_file(
                intent["connection"], expected_coordinator_id=intent["coordinator_id"]
            ) as client,
            CoordinatorOperatorClient.from_connection_file(
                intent["operator_connection"],
                expected_coordinator_id=intent["coordinator_id"],
            ) as operator,
        ):
            # Result downloads must not prevent other selected requests from dispatching.
            dispatch_results: dict[str, dict[str, Any]] = {}
            for check in ("cpu", "storage", "gpu"):
                if check not in intent["requests"]:
                    continue
                if previous_results.get(check, {}).get("outcome") == "failed":
                    continue
                if time.monotonic() >= deadline:
                    break
                dispatched = _dispatch_check(client, directory, intent, check)
                if dispatched is not None:
                    dispatch_results[check] = dispatched
            # Observe CPU/storage before GPU capacity waiting can exhaust the deadline.
            # Serialized intent key order is not execution order.
            for check in ("cpu", "storage", "gpu"):
                if check not in intent["requests"]:
                    continue
                request = intent["requests"][check]
                if previous_results.get(check, {}).get("outcome") == "failed":
                    results[check] = previous_results[check]
                    continue
                try:
                    result = dispatch_results.get(check) or (
                        _waiting("deadline_exceeded")
                        if time.monotonic() >= deadline
                        else _observe_check(
                            client, operator, directory, intent, check, deadline
                        )
                    )
                except CoordinatorClientError as exc:
                    result = {
                        "outcome": "unsupported"
                        if exc.code in {"unsupported", "unsupported_capability"}
                        else "waiting",
                        "code": exc.code,
                        "native_error": exc.to_dict(),
                    }
                results[check] = {
                    **result,
                    "operation_id": request["preparation"]["operation_id"],
                }
        outcomes = {row["outcome"] for row in results.values()} - {"not_requested"}
        outcome = next(
            (v for v in ("failed", "unsupported", "waiting") if v in outcomes), "passed"
        )
        result = {
            "schema_version": 1,
            "operation_id": operation_id,
            "agent_id": intent["agent_id"],
            "outcome": outcome,
            "checks": results,
            "ready": False,
            "scope": "requested_checks_only",
            "next": "Requested infrastructure checks passed; scientific accuracy is not tested."
            if outcome == "passed"
            else "Continue this operation ID; a failed check requires an explicit new attempt with --retry-of.",
        }
        temporary = directory / ("result-" + uuid4().hex + ".json")
        _publish(temporary, result)
        os.replace(temporary, directory / "result.json")
        return result
