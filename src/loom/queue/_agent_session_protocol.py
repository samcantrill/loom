"""Session decisions on the existing cooperative client owner.

Transport returns decoded replies or explicit uncertainty; this module owns
registration, offer and delivery replay without creating another mutable owner.
Public client entry points retain their serialization gates and progress lanes.
"""
from __future__ import annotations
from .gpu.occupancy import _sample_gpu_occupancy

from collections.abc import Callable, Generator, Mapping, Sequence

from dataclasses import replace

from uuid import uuid4

import json

from typing import Any, cast

from loom.serialization import PlainData

from loom.queue._managed_local import (
    AssignmentState,
    GpuResourceProvider,
    _ManagedApplicationSuspended,
)

from .agent_sessions import (
    AgentOffer,
    AgentOfferRenewal,
    AgentProviderDescriptor,
    AgentPollActiveError,
    AgentPollFencedError,
    AgentRegistration,
    AgentSession,
    PROTOCOL_VERSION,
    _session_from_value,
)

from ._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
)

from .errors import QueueConflictError, QueueServiceError

from ._agent_progress import _Progress, _steps, _external

from typing import TYPE_CHECKING
from ._agent_session_codec import _IndeterminateAgentProtocolError
if TYPE_CHECKING:
    from .agent_session_transport import LocalDaemonAgentHttpClient


def _raise_if_application_suspended(
    suspend_requested: Callable[[], bool] | None,
) -> None:
    if suspend_requested is not None and suspend_requested():
        raise _ManagedApplicationSuspended(
            "remote application stopped with supervised work retained"
        )


def handshake(self: LocalDaemonAgentHttpClient, *, role: str = "agent") -> Generator[_Progress, Any, Mapping[str, PlainData]]:
    if role not in {"agent", "client", "operator", "slurm_bootstrap"}:
        raise QueueServiceError("authenticated application role is invalid")
    result = (yield from _steps(self._call, "handshake", {}, role=role))
    if role == "agent":
        capabilities = result.get("capabilities")
        if (
            result.get("protocol_version") != PROTOCOL_VERSION
            or not isinstance(capabilities, Sequence)
            or isinstance(capabilities, (str, bytes))
            or any(not isinstance(item, str) for item in capabilities)
            or not {
                "agent-sessions-v12",
                REMOTE_EXECUTION_CAPABILITY,
                REGULAR_FILE_RELAY_CAPABILITY,
            }.issubset(set(capabilities))
        ):
            raise QueueServiceError(
                "agent coordinator protocol is unsupported; hard cut-over "
                f"requires version {PROTOCOL_VERSION}"
            )
        if "concurrent-resident-assignments-v1" not in capabilities:
            raise QueueServiceError(
                "coordinator upgrade required: missing concurrent-resident-assignments-v1"
            )
    return result


def register(self: LocalDaemonAgentHttpClient, request: AgentRegistration) -> Generator[_Progress, Any, AgentSession]:
    from .preparation import (
        PREPARATION_INPUT_CAPABILITY,
        PREPARATION_STAGED_INPUT_CAPABILITY,
    )
    from .retirement import require_unretired
    if self._config.agent_root is not None:
        require_unretired(self._config.agent_root)

    from ._shared_assignment import CAPABILITY
    from .shared_execution import SHARED_EXECUTION_CAPABILITY, qualifications
    if CAPABILITY in request.declared_capabilities:
        if CAPABILITY not in cast(Sequence[str], (yield from _steps(self.handshake))["capabilities"]):
            raise QueueServiceError("coordinator lacks shared-assignment-reference-v1")
        if SHARED_EXECUTION_CAPABILITY not in request.declared_capabilities:
            raise QueueServiceError("shared assignment references require shared execution")
        # Reference transport runs in this host application. Workers consume
        # the unchanged full bundle, so their existing qualification remains
        # sufficient, including installations retained for inline recovery.
    if SHARED_EXECUTION_CAPABILITY in request.declared_capabilities:
        if not any(profile.shared_roots for profile in self._profiles.values()):
            raise QueueServiceError("shared execution capability requires qualified roots")
        for profile in self._profiles.values():
            if not profile.shared_roots:
                continue
            if profile.readiness_result is None or not profile.readiness_result.ok or not any(check.check_id == "packages.shared_execution" and check.status.value == "PASS" for check in profile.readiness_result.checks):
                raise QueueServiceError("selected installation lacks shared execution qualification")
            if any("publication" in cast(Mapping[str, PlainData], root) for root in profile.shared_roots.values()) and not any(check.check_id == "packages.shared_publication" and check.status.value == "PASS" for check in profile.readiness_result.checks):
                raise QueueServiceError("selected installation lacks shared publication qualification")
            if (yield from _external("bulk", qualifications, profile.shared_roots)) != profile.descriptor.shared_roots:
                raise QueueServiceError("shared execution root qualification changed")
    staged = PREPARATION_STAGED_INPUT_CAPABILITY in request.declared_capabilities
    if (
        PREPARATION_INPUT_CAPABILITY in request.declared_capabilities or staged
    ) and (
        not self._profiles
        or any(
            profile.readiness_result is None
            or not profile.readiness_result.preparation_ready
            or (staged and not profile.readiness_result.preparation_staged_ready)
            for profile in self._profiles.values()
        )
    ):
        raise QueueServiceError(
            "preparation input capabilities require preparation qualification for their modes in each advertised resident environment"
        )
    journal = self._require_journal()
    persisted = journal.persist_registration_intent(request)
    session = _session_from_value((yield from _steps(self._call, "register", persisted.value())))
    journal.persist_session(persisted.idempotency_key, persisted.value(), session)
    return session


def _replay_pending_reconciliation(self: LocalDaemonAgentHttpClient):
    journal = self._require_journal()
    for operation_id, encoded in journal.pending_reconciliations():
        self._epoch_reconciliation_pending = True
        response = yield from _steps(self._call, "reconcile", json.loads(encoded))
        session = _session_from_value(response)
        journal.persist_reconciled_session(session)
        journal.complete_mutation("reconcile", operation_id, session.value())
        self._epoch_reconciliation_pending = False


def reconcile(
    self: LocalDaemonAgentHttpClient,
    session_id: str,
    coordinator_epoch: str,
    *,
    idempotency_key: str,
) -> Generator[_Progress, Any, AgentSession]:
    journal = self._require_journal()
    if self._service_progress:
        yield from _steps(self._replay_pending_reconciliation)
    expected = journal.session(session_id)
    if self._service_progress and expected.coordinator_epoch == coordinator_epoch:
        self._epoch_reconciliation_pending = False
        return expected
    candidates = [expected]
    if self._service_progress and self._execution_journal is not None:
        # An ordered release may have committed before its response was
        # lost and the coordinator restarted. Its exact durable revision is
        # the other possible session view, never a new capacity estimate.
        revisions = {
            self._execution_journal.read_availability_revision(assignment_id)
            for owner_session, assignment_id in journal.unresolved_assignment_references()
            if owner_session == session_id
            and self._execution_journal.find_state(assignment_id) is AssignmentState.RELEASED
        } - {None, expected.availability_revision}
        if len(revisions) == 1:
            candidates.insert(0, replace(expected, availability_revision=cast(str, next(iter(revisions)))))
    for index, candidate in enumerate(candidates):
        key = idempotency_key if index == 0 else idempotency_key + ":before-release"
        request: dict[str, PlainData] = {
            "expected": candidate.value(),
            "coordinator_epoch": coordinator_epoch,
            "idempotency_key": key,
        }
        journal._persist_mutation("reconcile", key, request)
        try:
            session = _session_from_value((yield from _steps(self._call, "reconcile", request)))
        except QueueConflictError:
            if index + 1 == len(candidates):
                raise
            # Only a definite rejection permits trying the pre-release
            # view. An uncertain exchange keeps retrying its original bytes.
            journal.discard_rejected_reconciliation(key)
            continue
        journal.persist_reconciled_session(session)
        journal.complete_mutation("reconcile", key, session.value())
        self._epoch_reconciliation_pending = False
        return session
    raise QueueConflictError("agent epoch reconciliation is unresolved")


def publish_offer(
    self: LocalDaemonAgentHttpClient,
    offer: AgentOffer,
    *,
    idempotency_key: str,
    expected_availability_revision: str | None = None,
    _observed_snapshot: bool = False,
) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
    if self._drained:
        raise QueueConflictError("drained agent cannot advertise capacity")
    if self._restart_with_retained_work:
        raise QueueConflictError(
            "restarted agent with retained remote work cannot advertise "
            "executable capacity"
        )
    if offer.resident_profiles:
        local_descriptors = {
            profile.descriptor.profile_id: profile
            for profile in self._profiles.values()
        }
        if any(
            local_descriptors.get(descriptor.profile_id) is None
            or local_descriptors[descriptor.profile_id].descriptor != descriptor
            for descriptor in offer.resident_profiles
        ):
            raise QueueConflictError("offer names an unavailable resident profile")
        capacity = self._config.capacity_profile
        if (
            offer.cpu > capacity.cpu_capacity
            or offer.memory_bytes > capacity.memory_capacity_bytes
            or tuple(
                sorted(
                    (device.descriptor for device in capacity.gpu_devices),
                    key=lambda item: item.device_id,
                )
            )
            != offer.gpu_devices
        ):
            raise QueueConflictError("offer exceeds the resident capacity domain")
        configured_gpu = {
            device.descriptor.device_id: device.descriptor.capacity_atom()
            for device in capacity.gpu_devices
        }
        if any(
            atom.local_capacity_key not in configured_gpu
            or atom.unit != configured_gpu[atom.local_capacity_key].unit
            or atom.granularity
            != configured_gpu[atom.local_capacity_key].granularity
            or atom.amount.fraction
            > configured_gpu[atom.local_capacity_key].amount.fraction
            for atom in offer.gpu_atoms
        ):
            raise QueueConflictError("offer exceeds the resident GPU capacity")
        factory = self._config.agent_resource_provider_factory
        if factory is None:
            raise QueueConflictError("remote agent provider composition is missing")
        self._provider_composition(
            self._require_journal().session(offer.session_id).agent_id,
            capacity,
        )
        if not _observed_snapshot:
            self._validate_offer_provider_capacity(
                offer,
                self._require_journal().session(offer.session_id).agent_id,
            )
        members = self._configured_provider_members
        if members is None:
            raise QueueConflictError("remote agent provider composition is missing")
        expected_provider_composition = tuple(
            sorted(
                (
                    AgentProviderDescriptor(
                        provider.descriptor, provider.claim_contracts
                    )
                    for provider in members
                ),
                key=lambda item: item.descriptor.key,
            )
        )
        if offer.provider_composition != expected_provider_composition:
            raise QueueConflictError(
                "offer provider identity differs from resident configuration"
            )
    if offer.external_slurm_profiles and (
        self._slurm_agent is None
        or not set(offer.external_slurm_profiles).issubset(
            self._slurm_agent.offered_profiles()
        )
    ):
        raise QueueConflictError("offer names an unavailable SLURM profile")
    journal = self._require_journal()
    journal.prepare_offer(offer, idempotency_key, expected_availability_revision)
    result = (yield from _steps(self._call,
        "offer",
        {
            "offer": offer.value(),
            "idempotency_key": idempotency_key,
            "expected_availability_revision": expected_availability_revision,
        },
    ))
    journal.complete_mutation("offer", idempotency_key, result)
    return result


def renew_offer(self: LocalDaemonAgentHttpClient, renewal: AgentOfferRenewal) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
    if self._drained or self._restart_with_retained_work:
        raise QueueConflictError("agent cannot renew executable capacity")
    journal = self._require_journal()
    operation_id = f"{renewal.session_id}:{renewal.offer_id}:{renewal.sequence}"
    journal._persist_mutation("renew", operation_id, renewal.value())
    replay = journal.prepare_offer_renewal(renewal)
    if replay is not None:
        journal.complete_mutation("renew", operation_id, replay)
        return replay
    result = (yield from _steps(self._call, "renew", {"renewal": renewal.value()}))
    journal.complete_offer_renewal(renewal, result)
    journal.complete_mutation("renew", operation_id, result)
    return result


def refresh_resource_offer(
    self: LocalDaemonAgentHttpClient, *, ttl_seconds: int = 30
) -> Generator[_Progress, Any, Mapping[str, PlainData] | None]:
    """Refresh cached host facts and report one serial, replayable resource view."""
    journal = self._require_journal()
    session = journal.active_session()
    if session is None or self._drained:
        return None
    if self._restart_with_retained_work and not self._service_progress:
        return None
    (yield from _steps(self._replay_pending_resource_mutation, session.session_id))
    session = journal.session(session.session_id)
    if not self._config.resident_profiles:
        if not (yield from _steps(self._qualify_service_admission)):
            return None
        profile = None
        descriptors, atoms, claims, statuses = (), (), (), ()
    else:
        profile = self._config.capacity_profile
        self._provider_composition(session.agent_id, profile)
        for provider in self._configured_provider_members or ():
            if isinstance(provider, GpuResourceProvider):
                monitor = provider._occupancy_monitor
                if monitor is not None:
                    cached = monitor.cached_snapshot()
                    if cached is None or not cached.is_fresh(monitor._monotonic_clock(), monitor.policy.poll_interval_seconds):
                        snapshot = yield from _external("bulk", _sample_gpu_occupancy,
                                                       monitor._observer, monitor.selected_uuids,
                                                       monitor._utc_clock, monitor._monotonic_clock)
                        monitor._apply_snapshot(snapshot)
        if not (yield from _steps(self._qualify_service_admission)):
            return None
        descriptors, atoms, claims, statuses = self._offer_provider_snapshot(
            session_id=session.session_id,
            availability_revision=session.availability_revision,
            capacity_profile=profile,
        )
    offer = AgentOffer(
        max_concurrent_assignments=self._config.max_concurrent_assignments,
        session_id=session.session_id,
        coordinator_epoch=session.coordinator_epoch,
        config_revision=session.config_revision,
        inventory_revision=session.inventory_revision,
        availability_revision=session.availability_revision,
        cpu=sum(
            atom.amount.numerator
            for atom in atoms
            if atom.owner_resource_kind == "cpu"
        ),
        memory_bytes=sum(
            atom.amount.numerator
            for atom in atoms
            if atom.owner_resource_kind == "memory"
        ),
        ttl_seconds=ttl_seconds,
        provider_composition=descriptors,
        pools=session.pools,
        reflected_claim_ids=claims,
        external_slurm_profiles=()
        if self._slurm_agent is None
        else self._slurm_agent.offered_profiles(),
        resident_profiles=tuple(
            item.descriptor for item in self._config.resident_profiles
        ),
        gpu_devices=()
        if profile is None
        else tuple(item.descriptor for item in profile.gpu_devices),
        gpu_atoms=tuple(
            atom for atom in atoms if atom.owner_resource_kind == "gpu"
        ),
        capacity_atoms=atoms,
        resource_status=statuses,
    )
    current = journal.current_resource_offer(session.session_id)
    renewal = journal.next_offer_renewal(session.session_id)
    if (
        current is not None
        and current.decision_value() == offer.decision_value()
        and renewal is not None
    ):
        return (yield from _steps(self.renew_offer, replace(renewal, resource_status=statuses)))
    expected = None
    if current is not None:
        expected = session.availability_revision
        offer = replace(offer, availability_revision=f"availability-{uuid4()}")
    return (yield from _steps(self.publish_offer,
        offer,
        idempotency_key=f"offer-{uuid4()}",
        expected_availability_revision=expected,
        _observed_snapshot=True,
    ))


def _replay_pending_resource_mutation(self: LocalDaemonAgentHttpClient, session_id: str) -> Generator[_Progress, Any, None]:
    """Resolve the exact report before another operation changes session state."""
    journal = self._require_journal()
    pending = journal.pending_resource_mutation(session_id)
    if pending is None:
        return
    operation, operation_id, value = pending
    try:
        if operation == "renew":
            renewal = AgentOfferRenewal.from_value(value)
            result = (yield from _steps(self._call, "renew", {"renewal": renewal.value()}))
        else:
            offered = dict(value)
            expected = offered.pop("expected_availability_revision", None)
            result = (yield from _steps(self._call,
                "offer",
                {
                    "offer": offered,
                    "idempotency_key": operation_id,
                    "expected_availability_revision": expected,
                },
            ))
    except _IndeterminateAgentProtocolError:
        raise
    except (QueueConflictError, QueueServiceError):
        # A definite rejection cannot later change capacity. Unknown transport
        # outcomes keep the exact intent for retry.
        journal.discard_rejected_resource_mutation(session_id, operation, operation_id)
        return
    if operation == "renew":
        journal.complete_offer_renewal(AgentOfferRenewal.from_value(value), result)
    journal.complete_mutation(operation, operation_id, result)


def renew_current_offer(self: LocalDaemonAgentHttpClient, session_id: str) -> Generator[_Progress, Any, Mapping[str, PlainData] | None]:
    renewal = self._require_journal().next_offer_renewal(session_id)
    return None if renewal is None else (yield from _steps(self.renew_offer, renewal))


def wait_for_work(
    self: LocalDaemonAgentHttpClient,
    session_id: str,
    availability_revision: str,
    *,
    sequence: int,
    wait_timeout_ms: int,
) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
    if self._drained:
        raise QueueConflictError("drained agent cannot poll for new work")
    if self._service_progress and not (yield from _steps(self._qualify_service_admission)):
        return {"result": "idle"}
    if self._restart_with_retained_work:
        raise QueueConflictError(
            "restarted agent with retained remote work cannot poll for new work"
        )
    if self._service_progress:
        journal = self._require_journal()
        current = journal.current_resource_offer(session_id)
        if current is None:
            self._next_resource_maintenance = 0
            return {"result": "idle"}
        availability_revision = journal.session(session_id).availability_revision
    value: dict[str, PlainData] = {
        "session_id": session_id,
        "availability_revision": availability_revision,
        "sequence": sequence,
        "wait_timeout_ms": wait_timeout_ms,
    }
    journal = self._require_journal()
    replay = journal.prepare_poll(
        session_id, availability_revision, sequence, value
    )
    if replay is not None:
        return replay
    try:
        result = (yield from _steps(self._call, "poll", value))
    except AgentPollActiveError:
        # The original held request still owns this exact poll identity.
        # Preserve the local intent so the same identity can be retried.
        raise
    except AgentPollFencedError:
        journal.fence_poll(session_id, sequence, confirmed=True)
        raise
    # Other rejection and indeterminate responses leave the exact request
    # pending. Only native outcome evidence proves sequence consumption.
    journal.complete_poll(session_id, sequence, result)
    return result


def _resume_pending_poll(
    self: LocalDaemonAgentHttpClient,
    *,
    wait_timeout_ms: int,
    suspend_requested: Callable[[], bool] | None = None,
) -> Generator[_Progress, Any, None]:
    """Replay the service's exact outstanding delivery before new capacity.

    The retained request digest validates the configured timeout as well as
    session/revision/sequence. An incompatible restart keeps work retained.
    A rejection is not consumption. Native outcome evidence settles the
    exact request or rewinds an absent legacy request to its proven owner
    watermark; a predecessor delivery must already be retained unchanged.
    """
    journal = self._require_journal()
    pending = journal.recovery_poll(wait_timeout_ms)
    if pending is None:
        return
    _raise_if_application_suspended(suspend_requested)
    state, value = pending
    session_id, sequence = str(value["session_id"]), int(cast(int, value["sequence"]))
    prior_epoch = journal.session(session_id).coordinator_epoch
    result: Mapping[str, PlainData] | None = None
    recover = state == "FENCED" or (yield from _steps(self.handshake))["coordinator_epoch"] != prior_epoch
    if not recover:
        try:
            result = (yield from _steps(self._call, "poll", value))
        except AgentPollActiveError:
            raise
        except AgentPollFencedError:
            journal.fence_poll(session_id, sequence, confirmed=True)
            return
        except _IndeterminateAgentProtocolError:
            raise
        except (QueueConflictError, QueueServiceError):
            recover = True
    if recover:
        recovery = (yield from _steps(self._call,
            "recover_poll", {**value, "coordinator_epoch": prior_epoch}
        ))
        if recovery.get("state") == "absent":
            journal.discard_absent_poll(
                session_id, sequence,
                predecessor_sequence=recovery.get("predecessor_sequence"),
                predecessor_delivery=recovery.get("predecessor_delivery"),
            )
            return
        if recovery.get("state") == "fenced":
            journal.fence_poll(session_id, sequence, confirmed=True)
            return
        if recovery.get("state") != "committed":
            raise QueueServiceError("retained poll recovery result is invalid")
        result = {key: item for key, item in recovery.items() if key != "state"}
    assert result is not None
    journal.complete_poll(session_id, sequence, result, recovered=True)
    if result.get("result") == "assignment" and not self._service_progress:
        request = (yield from _steps(self._resolve_delivery, session_id, result.get("request")))
        (yield from _steps(self._execute_delivered_assignment,
            session_id, request, suspend_requested=suspend_requested
        ))
