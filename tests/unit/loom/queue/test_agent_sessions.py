"""Focused no-launch tests for authenticated agent-session state."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
from pathlib import Path
from time import monotonic, sleep

import pytest

from loom.queue import (
    CoordinatorSchedulingReload,
    GpuDeviceDescriptor,
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    ResidentWorkerLaunchProfile,
)
from loom.queue._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    ResidentProfileDescriptor,
)
from loom.queue.agent_sessions import (
    AgentOffer,
    AgentOfferRenewal,
    AgentProviderDescriptor,
    AgentControl,
    AgentControlEffect,
    AgentControlKind,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentPollSequenceGapError,
    AgentRegistration,
    AgentRetirementProof,
    AgentSession,
    AgentSessionState,
    AgentStalePollError,
    SessionReplacementRequest,
    LocalOwnerOperatorPolicy,
    ScopedAuthorizer,
    TransportPrincipalPolicy,
    _REPLACEMENT_ASSIGNMENT_REFERENCE_CLASSES,
    _build_replacement_projection,
    initialize_agent_session_schema,
)
from loom.queue.errors import QueueConflictError, QueueServiceError, QueueStorageError
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData


_TEST_RETIREMENT_SECRET = "01" * 32
_TEST_RETIREMENT_VERIFIER = hashlib.sha256(
    bytes.fromhex(_TEST_RETIREMENT_SECRET)
).hexdigest()


def test_local_owner_scope_uses_verified_owner_subject_not_process_uid() -> None:
    policy = AgentPolicyConfig(
        local_owner=LocalOwnerOperatorPolicy(
            actions=("drain",), agent_ids=("agent-a",), pools=("default",)
        )
    )
    owner = LocalDaemonPrincipal("uid:verified-owner", LocalDaemonRole.OPERATOR)
    authorizer = ScopedAuthorizer(
        policy, verified_local_owner_subject="uid:verified-owner"
    )
    authorizer.require_operator(owner, "drain", agent_id="agent-a", pool="default")
    with pytest.raises(QueueServiceError, match="not authorized"):
        ScopedAuthorizer(
            policy, verified_local_owner_subject="uid:some-other-owner"
        ).require_operator(owner, "drain", agent_id="agent-a", pool="default")
    with pytest.raises(QueueServiceError, match="not authorized"):
        authorizer.require_operator(owner, "drain", agent_id="agent-b", pool="default")
    with pytest.raises(QueueServiceError, match="not authorized"):
        authorizer.require_operator(owner, "drain", agent_id="agent-a", pool="other")
    with pytest.raises(QueueServiceError, match="not authorized"):
        authorizer.require_operator(
            LocalDaemonPrincipal(
                "uid:verified-owner",
                LocalDaemonRole.OPERATOR,
                "remote-certificate",
            ),
            "drain",
            agent_id="agent-a",
            pool="default",
        )


def _replacement_projection_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_agent_session_schema(conn, coordinator=True)
    conn.execute(
        "CREATE TABLE recovery_operations (recovery_id TEXT PRIMARY KEY, "
        "principal_id TEXT NOT NULL, request_json TEXT NOT NULL, "
        "request_digest TEXT NOT NULL, recorded_at TEXT NOT NULL, "
        "state TEXT NOT NULL, evidence_json TEXT, result_json TEXT NOT NULL)"
    )
    return conn


def _replacement_projection_session() -> AgentSession:
    return AgentSession(
        session_id="session-old",
        coordinator_id="coordinator",
        coordinator_epoch="epoch",
        agent_id="agent-a",
        agent_root_id="root-old",
        policy_revision="policy",
        config_revision="config",
        inventory_revision="inventory",
        availability_revision="availability",
        capabilities=("python",),
        pools=("default",),
        state=AgentSessionState.ACTIVE,
    )


def _replacement_execution_fact(
    assignment_id: str, *, state: str = "released"
) -> dict[str, PlainData]:
    return {
        "assignment_id": assignment_id,
        "run_uri": "file:///run",
        "stage_work_id": f"work-{assignment_id}",
        "stage_name": "stage",
        "attempt": 1,
        "attempt_id": f"attempt-{assignment_id}",
        "agent_id": "agent-a",
        "session_id": "session-old",
        "offer_id": "offer-old",
        "claim_id": f"claim-{assignment_id}",
        "state": state,
        "receipt_digest": "a" * 64,
        "atom_count": 1,
        "atoms_digest": "b" * 64,
        "event_count": 0,
        "events_digest": "c" * 64,
    }


def _released_projection_assignment(
    conn: sqlite3.Connection, assignment_id: str
) -> None:
    conn.execute(
        "INSERT INTO remote_assignments(assignment_id, session_id, "
        "availability_revision, issuer_epoch, run_uri, stage_work_id, stage_name, "
        "attempt, attempt_id, profile_json, state) VALUES (?, 'session-old', "
        "'availability', 'epoch', 'file:///run', ?, 'stage', 1, ?, '{}', "
        "'RELEASED')",
        (assignment_id, f"work-{assignment_id}", f"attempt-{assignment_id}"),
    )
    conn.execute(
        "INSERT INTO agent_deliveries(assignment_id, session_id, "
        "availability_revision, coordinator_epoch, request_json, state) "
        "VALUES (?, 'session-old', 'availability', 'epoch', '{}', 'DELIVERED')",
        (assignment_id,),
    )
    conn.execute(
        "INSERT INTO agent_coordinator_references(session_id, reference_kind, "
        "reference_id, resolved) VALUES ('session-old', 'delivery', ?, 1)",
        (assignment_id,),
    )
    conn.executemany(
        "INSERT INTO agent_replacement_coverage(session_id, assignment_id, "
        "reference_class) VALUES ('session-old', ?, ?)",
        [
            (assignment_id, reference_class)
            for reference_class in _REPLACEMENT_ASSIGNMENT_REFERENCE_CLASSES
        ],
    )


def test_replacement_projection_requires_every_lost_agent_owner_class() -> None:
    conn = _replacement_projection_connection()
    _released_projection_assignment(conn, "assignment-one")
    fact = _replacement_execution_fact("assignment-one")
    projection = _build_replacement_projection(
        conn,
        session=_replacement_projection_session(),
        execution_facts=(fact,),
        observed_at="2026-01-01T00:00:00Z",
    )
    assert projection.required_claim_ids == ()
    counts = projection.value["owner_counts"]
    assert isinstance(counts, Mapping)
    assert counts["released"] == 1

    conn.execute(
        "DELETE FROM agent_replacement_coverage WHERE assignment_id = ? "
        "AND reference_class = 'outbox'",
        ("assignment-one",),
    )
    with pytest.raises(QueueConflictError, match="coverage is incomplete"):
        _build_replacement_projection(
            conn,
            session=_replacement_projection_session(),
            execution_facts=(fact,),
            observed_at="2026-01-01T00:00:00Z",
        )


def test_replacement_projection_rejects_execution_assignment_without_target() -> None:
    conn = _replacement_projection_connection()
    with pytest.raises(QueueConflictError, match="target inventory is incomplete"):
        _build_replacement_projection(
            conn,
            session=_replacement_projection_session(),
            execution_facts=(
                _replacement_execution_fact("assignment-new", state="bound"),
            ),
            observed_at="2026-01-01T00:00:00Z",
        )


def _provider_descriptors(*kinds: str) -> tuple[AgentProviderDescriptor, ...]:
    return tuple(
        AgentProviderDescriptor(
            SchedulingComponentDescriptor(
                kind, 1, "1", f"test-{kind}-provider", f"{kind}-configuration"
            ),
            (ResourceClaimContractDescriptor(kind, 1, f"builtin-{kind}-claim-v1"),),
        )
        for kind in sorted(kinds)
    )


def _policy(
    *, revision: str = "policy-1", credential: str = "agent-a"
) -> AgentPolicyConfig:
    return AgentPolicyConfig(
        revision=revision,
        agents=(
            AgentPrincipalPolicy(
                credential_id=credential,
                principal_id="principal-a",
                agent_id="agent-a",
                pools=("default",),
                capabilities=("python",),
            ),
        ),
        principals=(
            TransportPrincipalPolicy(
                "operator-credential",
                "operator",
                "operator",
                actions=(
                    "drain",
                    "resume",
                    "reload",
                    "cancel_active",
                    "scheduling_reload",
                    "replace_session",
                ),
                agent_ids=("agent-a",),
                pools=("default",),
            ),
        ),
    )


def test_query_transport_principal_is_role_exclusive() -> None:
    policy = TransportPrincipalPolicy("query-credential", "query", "query")
    assert policy.actions == ()
    assert policy.agent_ids == ()
    assert policy.pools == ()
    with pytest.raises(QueueServiceError, match="cannot define operator scopes"):
        TransportPrincipalPolicy(
            "query-credential", "query", "query", actions=("drain",)
        )


def _config(
    tmp_path: Path, policy: AgentPolicyConfig | None = None
) -> LocalDaemonConfig:
    return LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=_launch_profile(),
        agent_policy=_policy() if policy is None else policy,
    )


def _launch_profile() -> ResidentWorkerLaunchProfile:
    return ResidentWorkerLaunchProfile(
        project_root=Path.cwd(),
        python_executable=Path(sys.executable),
        descriptor=ResidentProfileDescriptor(
            "test-local", "v1", "test-project", "test-environment", "test-executor"
        ).to_dict(),
    )


def _view(daemon: LocalDaemon, credential: str = "agent-a"):
    return daemon.agent_view(
        LocalDaemonPrincipal("principal-a", LocalDaemonRole.AGENT, credential)
    )


def _register(daemon: LocalDaemon, *, key: str = "register-1"):
    handshake = _view(daemon).handshake()
    return _view(daemon).register(
        AgentRegistration(
            idempotency_key=key,
            coordinator_id=str(handshake["coordinator_id"]),
            coordinator_epoch=str(handshake["coordinator_epoch"]),
            agent_root_id="agent-root-a",
            config_revision="config-1",
            inventory_revision="inventory-1",
            availability_revision="availability-1",
            declared_pools=("default", "untrusted-pool"),
            declared_capabilities=("python", "untrusted"),
            retirement_verifier=_TEST_RETIREMENT_VERIFIER,
        )
    )


def _offer(
    session_id: str, epoch: str, *, availability: str = "availability-1"
) -> AgentOffer:
    return AgentOffer(
        session_id=session_id,
        coordinator_epoch=epoch,
        config_revision="config-1",
        inventory_revision="inventory-1",
        availability_revision=availability,
        cpu=2,
        memory_bytes=1024,
        ttl_seconds=30,
        provider_composition=_provider_descriptors("cpu", "memory"),
    )


def test_session_replacement_hard_cut_binds_fresh_successor_and_readiness(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        old = _register(daemon)
        operator = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        )
        pending = AgentControl(
            operation_id="replacement-pending-control",
            kind=AgentControlKind.DRAIN,
            agent_id=old.agent_id,
            expected_session_id=old.session_id,
            expected_config_revision=old.config_revision,
            pool="default",
            cancel_active=False,
            reason="lost agent",
        )
        operator.control_agent(pending)
        request = SessionReplacementRequest(
            "replace-agent-a", "agent-a", "lost agent root"
        )

        decision = operator.replace_agent_session(request)
        assert decision["state"] == "decision"
        assert decision["readiness"] == "withheld"
        assert decision["successor_session_id"] is None
        assert operator.replace_agent_session(request) == decision
        with pytest.raises(QueueConflictError, match="operation conflicts"):
            operator.replace_agent_session(replace(request, reason="changed"))
        with daemon._connection() as conn:
            assert (
                conn.execute(
                    "SELECT state FROM agent_sessions WHERE session_id = ?",
                    (old.session_id,),
                ).fetchone()[0]
                == AgentSessionState.REPLACED.value
            )
            assert (
                conn.execute(
                    "SELECT state FROM agent_controls WHERE operation_id = ?",
                    (pending.operation_id,),
                ).fetchone()[0]
                == "superseded"
            )

        with pytest.raises(QueueServiceError, match="not authorized"):
            _view(daemon).publish_offer(
                _offer(old.session_id, old.coordinator_epoch),
                idempotency_key="stale-old-offer",
            )
        handshake = _view(daemon).handshake()
        with pytest.raises(QueueConflictError, match="fresh root and revisions"):
            _view(daemon).register(
                AgentRegistration(
                    idempotency_key="replacement-stale-registration",
                    coordinator_id=str(handshake["coordinator_id"]),
                    coordinator_epoch=str(handshake["coordinator_epoch"]),
                    agent_root_id=old.agent_root_id,
                    config_revision=old.config_revision,
                    inventory_revision=old.inventory_revision,
                    availability_revision=old.availability_revision,
                    declared_pools=("default",),
                    declared_capabilities=("python",),
                    retirement_verifier=_TEST_RETIREMENT_VERIFIER,
                )
            )
        successor = _view(daemon).register(
            AgentRegistration(
                idempotency_key="replacement-fresh-registration",
                coordinator_id=str(handshake["coordinator_id"]),
                coordinator_epoch=str(handshake["coordinator_epoch"]),
                agent_root_id="agent-root-b",
                config_revision="config-2",
                inventory_revision="inventory-2",
                availability_revision="availability-2",
                declared_pools=("default",),
                declared_capabilities=("python",),
                retirement_verifier=hashlib.sha256(
                    bytes.fromhex("02" * 32)
                ).hexdigest(),
            )
        )
        assert successor.session_id != old.session_id
        with pytest.raises(QueueConflictError, match="readiness is still withheld"):
            _view(daemon).wait_for_work(
                successor.session_id,
                successor.availability_revision,
                sequence=1,
                wait_timeout_ms=10,
            )
        offer = replace(
            _offer(
                successor.session_id,
                successor.coordinator_epoch,
                availability="availability-2",
            ),
            config_revision="config-2",
            inventory_revision="inventory-2",
        )
        _view(daemon).publish_offer(
            offer, idempotency_key="replacement-first-observation"
        )
        with daemon._connection() as conn:
            row = conn.execute(
                "SELECT state, readiness, withholding_reason, result_json "
                "FROM session_replacements WHERE operation_id = ?",
                (request.operation_id,),
            ).fetchone()
        assert row is not None
        assert row["state"] == "ready"
        assert row["readiness"] == "ready"
        assert row["withholding_reason"] is None
        owner_counts = json.loads(str(row["result_json"]))["owner_counts"]
        assert isinstance(owner_counts, Mapping)
        assert owner_counts["assignments"] == 0
        assert (
            _view(daemon).wait_for_work(
                successor.session_id,
                successor.availability_revision,
                sequence=1,
                wait_timeout_ms=10,
            )["result"]
            == "wait"
        )
    finally:
        daemon.stop()


def test_session_replacement_rejects_empty_reachable_session(tmp_path: Path) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        session = _register(daemon)
        _view(daemon).publish_offer(
            _offer(session.session_id, session.coordinator_epoch),
            idempotency_key="reachable-offer",
        )
        with pytest.raises(QueueConflictError, match="clean retirement"):
            daemon.operator_view(
                LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
            ).replace_agent_session(
                SessionReplacementRequest(
                    "replace-reachable", session.agent_id, "not actually lost"
                )
            )
        with daemon._connection() as conn:
            assert (
                conn.execute(
                    "SELECT state FROM agent_sessions WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()[0]
                == AgentSessionState.ACTIVE.value
            )
    finally:
        daemon.stop()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unit", "cores"),
        ("granularity", {"numerator": 2, "denominator": 1}),
    ],
)
def test_offer_codec_rejects_noncanonical_capacity_atoms(
    field: str, value: PlainData
) -> None:
    encoded = _offer("session-1", "epoch-1").value()
    atoms = encoded["capacity_atoms"]
    assert isinstance(atoms, list)
    first = atoms[0]
    assert isinstance(first, dict)
    first[field] = value

    with pytest.raises(QueueServiceError, match="capacity is invalid"):
        AgentOffer.from_value(encoded)


def test_offer_codec_preserves_physical_capacity_atom_identity() -> None:
    original = _offer("session-1", "epoch-1")
    offer = replace(
        original,
        capacity_atoms=(
            CapacityAtom("cpu", "cpu-a", ExactQuantity(1), "count", ExactQuantity(1)),
            CapacityAtom("cpu", "cpu-b", ExactQuantity(1), "count", ExactQuantity(1)),
            CapacityAtom(
                "memory",
                "memory",
                ExactQuantity(1024),
                "byte",
                ExactQuantity(1),
            ),
        ),
    )

    assert AgentOffer.from_value(offer.value()) == offer


def test_offer_checks_each_physical_provider_only_against_its_kind(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        session = _register(daemon)
        base = _offer(session.session_id, session.coordinator_epoch)
        cpu_contract = ResourceClaimContractDescriptor("cpu", 1, "builtin-cpu-claim-v1")
        memory_provider = _provider_descriptors("memory")[0]
        cpu_providers = tuple(
            AgentProviderDescriptor(
                SchedulingComponentDescriptor(
                    "cpu", 1, "1", f"test-cpu-provider-{suffix}", suffix
                ),
                (cpu_contract,),
            )
            for suffix in ("a", "b")
        )
        multi_provider = replace(
            base,
            provider_composition=(*cpu_providers, memory_provider),
        )

        accepted = _view(daemon).publish_offer(
            multi_provider, idempotency_key="multi-provider-offer"
        )
        assert accepted["state"] == "retained"

        incompatible = replace(
            base,
            provider_composition=(
                AgentProviderDescriptor(
                    cpu_providers[0].descriptor,
                    (ResourceClaimContractDescriptor("cpu", 1, "incompatible"),),
                ),
                memory_provider,
            ),
        )
        with pytest.raises(QueueServiceError, match="no claim-contract intersection"):
            _view(daemon).publish_offer(
                incompatible, idempotency_key="incompatible-provider-offer"
            )

        synthetic = AgentOffer(
            session.session_id,
            session.coordinator_epoch,
            session.config_revision,
            session.inventory_revision,
            session.availability_revision,
            0,
            0,
            30,
            (
                AgentProviderDescriptor(
                    SchedulingComponentDescriptor(
                        "synthetic", 1, "1", "test-synthetic-provider", "configured"
                    ),
                    (ResourceClaimContractDescriptor("synthetic", 1, "synthetic-v1"),),
                ),
            ),
            capacity_atoms=(
                CapacityAtom(
                    "synthetic",
                    "token-1",
                    ExactQuantity(1),
                    "token",
                    ExactQuantity(1),
                ),
            ),
        )
        with pytest.raises(QueueServiceError, match="no active planner"):
            _view(daemon).publish_offer(
                synthetic, idempotency_key="unknown-provider-offer"
            )
    finally:
        daemon.stop()


def _proof(session) -> AgentRetirementProof:
    return AgentRetirementProof(
        session_id=session.session_id,
        coordinator_id=session.coordinator_id,
        coordinator_epoch=session.coordinator_epoch,
        agent_id=session.agent_id,
        agent_root_id=session.agent_root_id,
        policy_revision=session.policy_revision,
        config_revision=session.config_revision,
        inventory_revision=session.inventory_revision,
        availability_revision=session.availability_revision,
        reference_revision=0,
        reference_digest="a" * 64,
        retirement_secret=_TEST_RETIREMENT_SECRET,
    )


def _sqlite_snapshot(path: Path) -> tuple[str, ...]:
    with sqlite3.connect(path) as conn:
        return tuple(conn.iterdump())


def _file_snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (str(path.relative_to(root)), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def test_registration_replay_is_coordinator_issued_and_digest_bound(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        replay = _register(daemon)
        assert replay.session_id == registered.session_id
        assert registered.session_id.startswith("session-")
        assert registered.capabilities == ("python",)
        assert registered.pools == ("default",)
        with pytest.raises(QueueConflictError, match="different content"):
            _view(daemon).register(
                AgentRegistration(
                    idempotency_key="register-1",
                    coordinator_id=registered.coordinator_id,
                    coordinator_epoch=registered.coordinator_epoch,
                    agent_root_id=registered.agent_root_id,
                    config_revision="changed",
                    inventory_revision="inventory-1",
                    availability_revision="availability-1",
                    declared_pools=("default",),
                    retirement_verifier=_TEST_RETIREMENT_VERIFIER,
                )
            )
        with pytest.raises(QueueConflictError, match="cannot select"):
            _view(daemon).register(
                AgentRegistration(
                    idempotency_key="register-2",
                    coordinator_id=registered.coordinator_id,
                    coordinator_epoch=registered.coordinator_epoch,
                    agent_root_id=registered.agent_root_id,
                    config_revision="config-1",
                    inventory_revision="inventory-1",
                    availability_revision="availability-1",
                    declared_pools=("default",),
                    session_id="caller-session",
                    retirement_verifier=_TEST_RETIREMENT_VERIFIER,
                )
            )
    finally:
        daemon.stop()


def test_agent_control_withdraws_offer_then_requires_agent_acknowledgement(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        session = _register(daemon)
        _view(daemon).publish_offer(
            _offer(session.session_id, session.coordinator_epoch),
            idempotency_key="offer-control",
        )
        control = AgentControl(
            operation_id="control-1",
            kind=AgentControlKind.DRAIN,
            agent_id=session.agent_id,
            expected_session_id=session.session_id,
            expected_config_revision=session.config_revision,
            pool="default",
            cancel_active=False,
            reason="maintenance",
        )
        operator = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        )
        assert operator.control_agent(control)["state"] == "pending_delivery"
        delivered = _view(daemon).next_control(session.session_id)
        assert delivered == control
        with pytest.raises(QueueConflictError, match="still in progress"):
            operator.control_agent(
                replace(
                    control,
                    operation_id="control-2",
                    kind=AgentControlKind.RESUME,
                    pool=None,
                )
            )
        assert (
            _view(daemon).acknowledge_control(
                session.session_id,
                AgentControlEffect(
                    operation_id=control.operation_id,
                    code="applied",
                    config_revision=session.config_revision,
                    inventory_revision=session.inventory_revision,
                    availability_revision="availability-drained",
                ),
            )["state"]
            == "applied"
        )
        with daemon._connection() as conn:
            assert (
                conn.execute(
                    "SELECT current FROM agent_offers WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()[0]
                == 0
            )
    finally:
        daemon.stop()


def test_completed_agent_reload_replays_before_the_old_session_revision_is_checked(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        session = _register(daemon)
        control = AgentControl(
            operation_id="reload-control-replay",
            kind=AgentControlKind.RELOAD,
            agent_id=session.agent_id,
            expected_session_id=session.session_id,
            expected_config_revision=session.config_revision,
            pool=None,
            cancel_active=False,
            reason="replace trusted provider config",
        )
        operator = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        )
        assert operator.control_agent(control)["state"] == "pending_delivery"
        assert _view(daemon).next_control(session.session_id) == control
        receipt = _view(daemon).acknowledge_control(
            session.session_id,
            AgentControlEffect(
                operation_id=control.operation_id,
                code="applied",
                config_revision="config-2",
                inventory_revision="inventory-2",
                availability_revision="availability-2",
            ),
        )

        assert operator.control_agent(control) == receipt
        assert receipt["state"] == "applied"
    finally:
        daemon.stop()


@pytest.mark.parametrize(
    ("actions", "agent_ids", "pools", "cancel_active"),
    [
        (("resume",), ("agent-a",), ("default",), False),
        (("drain",), ("another-agent",), ("default",), False),
        (("drain",), ("agent-a",), ("another-pool",), False),
        (("drain",), ("agent-a",), ("default",), True),
    ],
)
def test_operator_control_scope_denial_happens_before_control_persistence(
    tmp_path: Path,
    actions: tuple[str, ...],
    agent_ids: tuple[str, ...],
    pools: tuple[str, ...],
    cancel_active: bool,
) -> None:
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy(
                "operator-credential",
                "operator",
                "operator",
                actions=actions,
                agent_ids=agent_ids,
                pools=pools,
            ),
        ),
    )
    config = _config(tmp_path, policy)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        session = _register(daemon)
        control = AgentControl(
            operation_id="denied-control",
            kind=AgentControlKind.DRAIN,
            agent_id=session.agent_id,
            expected_session_id=session.session_id,
            expected_config_revision=session.config_revision,
            pool="default",
            cancel_active=cancel_active,
            reason="out-of-scope",
        )
        operator = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        )
        with pytest.raises(QueueServiceError, match="not authorized"):
            operator.control_agent(control)
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM agent_controls").fetchone()[0] == 0
            )
    finally:
        daemon.stop()


def test_remote_start_permit_serializes_with_cancellation_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
    )
    policy = AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                credential_id="agent-a",
                principal_id="principal-a",
                agent_id="agent-a",
                pools=("default",),
                capabilities=capabilities,
            ),
        )
    )
    config = _config(tmp_path, policy)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        handshake = _view(daemon).handshake()
        session = _view(daemon).register(
            AgentRegistration(
                idempotency_key="register-start-permit",
                coordinator_id=str(handshake["coordinator_id"]),
                coordinator_epoch=str(handshake["coordinator_epoch"]),
                agent_root_id="agent-root-start-permit",
                config_revision="config-1",
                inventory_revision="inventory-1",
                availability_revision="availability-1",
                declared_pools=("default",),
                declared_capabilities=capabilities,
                retirement_verifier=_TEST_RETIREMENT_VERIFIER,
            )
        )
        with daemon._connection() as conn:
            for assignment_id, run_uri in (
                ("assignment-permitted", "run://permitted"),
                ("assignment-cancelled", "run://cancelled"),
            ):
                conn.execute(
                    "INSERT INTO remote_assignments(assignment_id, session_id, "
                    "availability_revision, issuer_epoch, run_uri, stage_work_id, "
                    "stage_name, attempt, attempt_id, profile_json, state, fence) "
                    "VALUES (?, ?, 'availability-1', ?, ?, ?, 'stage', 1, ?, '{}', "
                    "'GRANTED', ?)",
                    (
                        assignment_id,
                        session.session_id,
                        session.coordinator_epoch,
                        run_uri,
                        f"work-{assignment_id}",
                        f"attempt-{assignment_id}",
                        f"fence-{assignment_id}",
                    ),
                )
            conn.execute(
                "INSERT INTO managed_admissions(admission_id, queue_item_id, "
                "coordinator_id, run_uri, intent_digest, execution_owner, state, "
                "accepted_at, authority_operation_id, run_priority, "
                "enqueue_sequence, cancellation_operation_id) "
                "VALUES ('admission-cancelled', 'item-cancelled', ?, "
                "'run://cancelled', 'digest', 'managed-stage', 'CANCELLED', ?, "
                "'authority-op', 0, 1, 'cancel-op')",
                (str(handshake["coordinator_id"]), "2020-01-01T00:00:00Z"),
            )
            conn.commit()

        execution = daemon._execution
        assert execution is not None
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            execution,
            "remote_start_permit",
            lambda assignment_id, *, fence: (
                calls.append((assignment_id, fence)) or True
            ),
        )
        assert _view(daemon).start_permit(
            session.session_id,
            "assignment-permitted",
            fence="fence-assignment-permitted",
        )
        assert not _view(daemon).start_permit(
            session.session_id,
            "assignment-cancelled",
            fence="fence-assignment-cancelled",
        )
        assert calls == [("assignment-permitted", "fence-assignment-permitted")]
        with daemon._connection() as conn:
            rows = dict(
                conn.execute(
                    "SELECT assignment_id, start_permitted FROM remote_assignments"
                )
            )
        assert rows == {
            "assignment-permitted": 1,
            "assignment-cancelled": 0,
        }
    finally:
        daemon.stop()


def test_scheduling_reload_rejects_credential_change_for_a_live_agent_session(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, _policy())
    replacement = replace(
        config,
        agent_policy=_policy(revision="policy-2", credential="agent-b"),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, trusted_scheduling_loader=lambda: replacement)
    before = daemon.start()
    try:
        _register(daemon)
        result = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        ).reload_scheduling(
            CoordinatorSchedulingReload(
                operation_id="reload-live-agent-policy",
                expected_scheduling_epoch=before.scheduling_epoch,
                reason="rotate agent credential",
            )
        )
        assert result["state"] == "failed"
        assert result["code"] == "reload_rejected"
        assert daemon.config is config
    finally:
        daemon.stop()


def test_policy_removal_fences_existing_session_and_overlap_reconciles(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        daemon.replace_agent_policy(AgentPolicyConfig(revision="policy-2"))
        with pytest.raises(QueueServiceError, match="not authorized"):
            _view(daemon).publish_offer(
                _offer(registered.session_id, registered.coordinator_epoch),
                idempotency_key="offer-1",
            )
        overlap = AgentPolicyConfig(
            revision="policy-3",
            agents=(
                AgentPrincipalPolicy(
                    "agent-b", "principal-a", "agent-a", ("default",), ("python",)
                ),
            ),
        )
        daemon.replace_agent_policy(overlap)
        resumed = _view(daemon, "agent-b").reconcile(
            registered,
            registered.coordinator_epoch,
            idempotency_key="reconcile-1",
        )
        assert resumed.session_id == registered.session_id
        assert resumed.policy_revision == "policy-3"
    finally:
        daemon.stop()


def test_restart_requires_reconcile_fresh_offer_and_only_returns_wait(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    first = LocalDaemon(config)
    first.start()
    registered = _register(first)
    first.stop()

    second = LocalDaemon(config)
    second.start()
    try:
        handshake = _view(second).handshake()
        epoch = str(handshake["coordinator_epoch"])
        assert epoch != registered.coordinator_epoch
        replayed = _view(second).register(
            AgentRegistration(
                idempotency_key="register-1",
                coordinator_id=registered.coordinator_id,
                coordinator_epoch=registered.coordinator_epoch,
                agent_root_id=registered.agent_root_id,
                config_revision=registered.config_revision,
                inventory_revision=registered.inventory_revision,
                availability_revision=registered.availability_revision,
                declared_pools=("default", "untrusted-pool"),
                declared_capabilities=("python", "untrusted"),
                retirement_verifier=_TEST_RETIREMENT_VERIFIER,
            )
        )
        assert replayed == registered
        with pytest.raises(QueueConflictError, match="epoch"):
            _view(second).publish_offer(
                _offer(registered.session_id, registered.coordinator_epoch),
                idempotency_key="offer-stale",
            )
        resumed = _view(second).reconcile(
            registered, epoch, idempotency_key="reconcile-1"
        )
        offer = _view(second).publish_offer(
            _offer(resumed.session_id, epoch), idempotency_key="offer-1"
        )
        assert offer["state"] == "retained"
        wait = _view(second).wait_for_work(
            resumed.session_id,
            "availability-1",
            sequence=1,
            wait_timeout_ms=5,
        )
        assert wait == {
            "result": "wait",
            "sequence": 1,
            "coordinator_epoch": epoch,
        }

        # The restricted view cannot touch the Phase 3 execution owners.
        with sqlite3.connect(config.execution_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM coordinator_assignments").fetchone()[
                    0
                ]
                == 0
            )
            assert (
                conn.execute("SELECT COUNT(*) FROM coordinator_offers").fetchone()[0]
                == 0
            )
    finally:
        second.stop()


def test_restart_fences_abandoned_poll_before_fresh_offer(tmp_path: Path) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    first = LocalDaemon(config)
    first.start()
    registered = _register(first)
    _view(first).publish_offer(
        _offer(registered.session_id, registered.coordinator_epoch),
        idempotency_key="offer-before-restart",
    )
    with first._connection() as conn:
        conn.execute(
            "INSERT INTO agent_poll_state(principal_id, session_id, sequence, "
            "availability_revision, coordinator_epoch, wait_timeout_ms, digest, "
            "active, result_json) VALUES (?, ?, 1, ?, ?, 1000, 'abandoned', 1, NULL)",
            (
                "principal-a",
                registered.session_id,
                registered.availability_revision,
                registered.coordinator_epoch,
            ),
        )
        conn.commit()
    first.stop()

    second = LocalDaemon(config)
    status = second.start()
    try:
        resumed = _view(second).reconcile(
            registered,
            status.coordinator_epoch,
            idempotency_key="reconcile-after-abandoned-poll",
        )
        offer = _view(second).publish_offer(
            _offer(resumed.session_id, resumed.coordinator_epoch),
            idempotency_key="offer-after-abandoned-poll",
        )
        assert offer["state"] == "retained"
        assert _view(second).wait_for_work(
            resumed.session_id,
            resumed.availability_revision,
            sequence=2,
            wait_timeout_ms=5,
        ) == {
            "result": "wait",
            "sequence": 2,
            "coordinator_epoch": status.coordinator_epoch,
        }
    finally:
        second.stop()


def test_retirement_fences_then_requires_empty_coordinator_references_and_tombstones(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        reconciled = _view(daemon).reconcile(
            registered,
            registered.coordinator_epoch,
            idempotency_key="reconcile-before-retire",
        )
        proof = _proof(reconciled)
        _view(daemon).publish_offer(
            _offer(registered.session_id, registered.coordinator_epoch),
            idempotency_key="offer-1",
        )
        with pytest.raises(QueueConflictError, match="proof is stale"):
            _view(daemon).retire_clean(
                replace(proof, agent_root_id="replacement-root"),
                idempotency_key="retire-wrong-root",
            )
        with daemon._connection() as conn:  # coordinator-owned known reference
            conn.execute(
                "INSERT INTO agent_poll_state(principal_id, session_id, sequence, "
                "availability_revision, coordinator_epoch, wait_timeout_ms, "
                "digest, active, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL)",
                (
                    "principal-a",
                    registered.session_id,
                    1,
                    registered.availability_revision,
                    registered.coordinator_epoch,
                    100,
                    "digest",
                ),
            )
            conn.execute(
                "INSERT INTO agent_coordinator_references(session_id, reference_kind, reference_id, resolved) VALUES (?, ?, ?, 0)",
                (registered.session_id, "outbox", "event-1"),
            )
            conn.commit()
        with pytest.raises(QueueConflictError, match="unresolved"):
            _view(daemon).retire_clean(proof, idempotency_key="retire-1")
        with daemon._connection() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_offers WHERE current = 1"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_poll_state WHERE active = 1"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute("SELECT state FROM agent_sessions").fetchone()[0]
                == "RETIRING"
            )
            conn.execute("UPDATE agent_coordinator_references SET resolved = 1")
            conn.commit()
        daemon.stop()
        daemon.replace_agent_policy(
            AgentPolicyConfig(
                revision="policy-2",
                agents=(
                    AgentPrincipalPolicy(
                        "agent-b",
                        "principal-a",
                        "agent-a",
                        ("default",),
                        ("python",),
                    ),
                ),
            )
        )
        daemon.start()
        retired = _view(daemon, "agent-b").retire_clean(
            proof, idempotency_key="retire-1"
        )
        assert retired["state"] == AgentSessionState.RETIRED_CLEAN.value
        with daemon._connection() as conn:
            assert (
                conn.execute("SELECT state FROM agent_session_tombstones").fetchone()[0]
                == "RETIRED_CLEAN"
            )
        original_registration = AgentRegistration(
            idempotency_key="register-1",
            coordinator_id=registered.coordinator_id,
            coordinator_epoch=registered.coordinator_epoch,
            agent_root_id=registered.agent_root_id,
            config_revision=registered.config_revision,
            inventory_revision=registered.inventory_revision,
            availability_revision=registered.availability_revision,
            declared_pools=("default", "untrusted-pool"),
            declared_capabilities=("python", "untrusted"),
            retirement_verifier=_TEST_RETIREMENT_VERIFIER,
        )
        with pytest.raises(QueueConflictError, match="no longer actionable"):
            _view(daemon, "agent-b").register(original_registration)
        with pytest.raises(QueueConflictError, match="no longer actionable"):
            _view(daemon, "agent-b").reconcile(
                registered,
                registered.coordinator_epoch,
                idempotency_key="reconcile-before-retire",
            )
    finally:
        daemon.stop()


def test_retirement_secret_rejects_before_mutation_and_is_redacted(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        session = _register(daemon)
        _view(daemon).publish_offer(
            _offer(session.session_id, session.coordinator_epoch),
            idempotency_key="offer-secret-proof",
        )
        proof = _proof(session)
        before = _sqlite_snapshot(config.control_database)
        with pytest.raises(QueueServiceError, match="proof is invalid"):
            _view(daemon).retire_clean(
                replace(proof, retirement_secret="02" * 32),
                idempotency_key="retire-wrong-secret",
            )
        assert _sqlite_snapshot(config.control_database) == before

        _view(daemon).retire_clean(proof, idempotency_key="retire-right-secret")
        coordinator_state = "\n".join(_sqlite_snapshot(config.control_database))
        assert _TEST_RETIREMENT_SECRET not in coordinator_state
        assert '"retirement_secret"' not in coordinator_state
    finally:
        daemon.stop()


def test_offer_renewal_is_sequenced_replayed_and_retains_one_offer(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    now = ["2026-01-01T00:00:00Z"]
    daemon = LocalDaemon(config, clock=lambda: now[0])
    daemon.start()
    try:
        session = _register(daemon)
        published = _view(daemon).publish_offer(
            _offer(session.session_id, session.coordinator_epoch),
            idempotency_key="offer-renewal",
        )
        renewal = AgentOfferRenewal(
            session.session_id, str(published["offer_id"]), "availability-1", 1
        )
        now[0] = "2026-01-01T00:00:10Z"
        first = _view(daemon).renew_offer(renewal)
        assert _view(daemon).renew_offer(renewal) == first
        _view(daemon).renew_offer(replace(renewal, sequence=2))
        with pytest.raises(AgentPollSequenceGapError, match="gap"):
            _view(daemon).renew_offer(replace(renewal, sequence=4))
        with pytest.raises(AgentStalePollError, match="stale"):
            _view(daemon).renew_offer(renewal)
        with daemon._connection() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_offers WHERE session_id = ? AND current = 1",
                    (session.session_id,),
                ).fetchone()[0]
                == 1
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_offer_renewals WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()[0]
                == 1
            )
            conn.execute(
                "UPDATE agent_sessions SET availability_revision = ? "
                "WHERE session_id = ?",
                ("availability-2", session.session_id),
            )
            conn.commit()
        replacement = _view(daemon).publish_offer(
            _offer(
                session.session_id,
                session.coordinator_epoch,
                availability="availability-2",
            ),
            idempotency_key="offer-renewal-replacement",
        )
        restarted_sequence = AgentOfferRenewal(
            session.session_id,
            str(replacement["offer_id"]),
            "availability-2",
            1,
        )
        assert _view(daemon).renew_offer(restarted_sequence)["sequence"] == 1
        with daemon._connection() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_offer_renewals WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()[0]
                == 1
            )
    finally:
        daemon.stop()


def test_offer_expiry_and_stale_poll_fail_without_touching_execution_owners(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    now = ["2026-01-01T00:00:00Z"]
    daemon = LocalDaemon(config, clock=lambda: now[0])
    daemon.start()
    try:
        registered = _register(daemon)
        _view(daemon).publish_offer(
            AgentOffer(
                registered.session_id,
                registered.coordinator_epoch,
                "config-1",
                "inventory-1",
                "availability-1",
                1,
                1,
                1,
                _provider_descriptors("cpu", "memory"),
            ),
            idempotency_key="offer-1",
        )
        now[0] = "2026-01-01T00:00:02Z"
        with pytest.raises(QueueConflictError, match="current offer"):
            _view(daemon).wait_for_work(
                registered.session_id,
                "availability-1",
                sequence=1,
                wait_timeout_ms=5,
            )
        with pytest.raises(QueueConflictError, match="availability revision"):
            _view(daemon).wait_for_work(
                registered.session_id,
                "availability-2",
                sequence=1,
                wait_timeout_ms=5,
            )
        with sqlite3.connect(config.execution_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM coordinator_assignments").fetchone()[
                    0
                ]
                == 0
            )
    finally:
        daemon.stop()


def test_offer_wire_shape_uses_bounded_exact_capacity_atoms() -> None:
    value = _offer("session-1", "epoch-1").value()
    assert "cpu" not in value and "memory_bytes" not in value
    atoms = value["capacity_atoms"]
    assert isinstance(atoms, list)
    assert atoms == [
        {
            "owner_resource_kind": "cpu",
            "local_capacity_key": "cpu",
            "amount": {"numerator": 2, "denominator": 1},
            "unit": "count",
            "granularity": {"numerator": 1, "denominator": 1},
        },
        {
            "owner_resource_kind": "memory",
            "local_capacity_key": "memory",
            "amount": {"numerator": 1024, "denominator": 1},
            "unit": "byte",
            "granularity": {"numerator": 1, "denominator": 1},
        },
    ]


def test_gpu_offer_has_one_strict_exact_round_trip_without_private_binding() -> None:
    device = GpuDeviceDescriptor(
        "safe-gpu", "large", 80 * 1024**3, fabric_group="fabric-a"
    )
    offer = AgentOffer(
        "session-1",
        "epoch-1",
        "config-1",
        "inventory-1",
        "availability-1",
        0,
        0,
        30,
        _provider_descriptors("gpu"),
        gpu_devices=(device,),
        gpu_atoms=(device.capacity_atom(),),
    )

    encoded = offer.value()
    assert AgentOffer.from_value(encoded) == offer
    assert "binding" not in repr(encoded).lower()

    old_descriptor = device.to_dict()
    del old_descriptor["fabric_group"]
    with pytest.raises(QueueServiceError, match="descriptor is invalid"):
        GpuDeviceDescriptor.from_dict(old_descriptor)
    old_offer = offer.value()
    old_offer["provider_descriptors"] = old_offer.pop("provider_composition")
    with pytest.raises(QueueServiceError, match="agent offer is invalid"):
        AgentOffer.from_value(old_offer)

    atoms = encoded["capacity_atoms"]
    assert isinstance(atoms, list)
    gpu_atom = atoms[0]
    assert isinstance(gpu_atom, dict)
    gpu_atom["amount"] = {"numerator": 2, "denominator": 1}
    with pytest.raises(QueueServiceError, match="conflicts with configured inventory"):
        AgentOffer.from_value(encoded)


def test_gpu_offer_rejects_old_or_policy_different_inventory(tmp_path: Path) -> None:
    device = GpuDeviceDescriptor("safe-gpu", "large", 80 * 1024**3)
    policy = AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                "agent-a",
                "principal-a",
                "agent-a",
                ("default",),
                ("python",),
                (device,),
            ),
        )
    )
    config = _config(tmp_path, policy)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        accepted = AgentOffer(
            registered.session_id,
            registered.coordinator_epoch,
            "config-1",
            "inventory-1",
            "availability-1",
            1,
            0,
            30,
            _provider_descriptors("cpu", "gpu"),
            gpu_devices=(device,),
            gpu_atoms=(device.capacity_atom(),),
        )
        _view(daemon).publish_offer(accepted, idempotency_key="gpu-offer")
        different = replace(
            accepted,
            gpu_devices=(GpuDeviceDescriptor("other-gpu", "large", 80 * 1024**3),),
            gpu_atoms=(),
            capacity_atoms=tuple(
                atom
                for atom in accepted.capacity_atoms
                if atom.owner_resource_kind != "gpu"
            ),
        )
        with pytest.raises(QueueConflictError, match="protected policy"):
            _view(daemon).publish_offer(
                different, idempotency_key="different-gpu-offer"
            )

        old_shape = accepted.value()
        del old_shape["gpu_devices"]
        old_shape["gpu"] = {"device_id": "safe-gpu"}
        with pytest.raises(QueueServiceError, match="agent offer is invalid"):
            AgentOffer.from_value(old_shape)
    finally:
        daemon.stop()


def test_production_policy_rejects_unenforced_gpu_sharing() -> None:
    shared = GpuDeviceDescriptor(
        "safe-gpu",
        "large",
        80 * 1024**3,
        allocation_mode="vram_share",
        provider="configured-share-provider",
        granularity=1024**3,
    )
    with pytest.raises(QueueServiceError, match="enforceable provider adapter"):
        AgentPrincipalPolicy(
            "agent-a",
            "principal-a",
            "agent-a",
            ("default",),
            ("python",),
            (shared,),
        )


def test_gpu_fraction_descriptor_uses_one_canonical_rational_shape() -> None:
    descriptor = GpuDeviceDescriptor(
        "safe-gpu",
        "partitioned",
        80 * 1024**3,
        allocation_mode="provider_fraction",
        provider="configured-fraction-provider",
        share_numerator=2,
        share_denominator=4,
        share_granularity_numerator=2,
        share_granularity_denominator=8,
    )

    assert (descriptor.share_numerator, descriptor.share_denominator) == (1, 2)
    assert (
        descriptor.share_granularity_numerator,
        descriptor.share_granularity_denominator,
    ) == (1, 4)
    assert GpuDeviceDescriptor.from_dict(descriptor.to_dict()) == descriptor


def test_wait_poll_is_sequenced_replayed_and_current_policy_is_rechecked(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        _view(daemon).publish_offer(
            _offer(registered.session_id, registered.coordinator_epoch),
            idempotency_key="offer-1",
        )
        first = _view(daemon).wait_for_work(
            registered.session_id,
            "availability-1",
            sequence=1,
            wait_timeout_ms=10,
        )
        assert (
            _view(daemon).wait_for_work(
                registered.session_id,
                "availability-1",
                sequence=1,
                wait_timeout_ms=10,
            )
            == first
        )
        with pytest.raises(QueueConflictError, match="different content"):
            _view(daemon).wait_for_work(
                registered.session_id,
                "availability-1",
                sequence=1,
                wait_timeout_ms=11,
            )

        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(
                _view(daemon).wait_for_work,
                registered.session_id,
                "availability-1",
                sequence=2,
                wait_timeout_ms=1_000,
            )
            deadline = monotonic() + 2
            while monotonic() < deadline:
                with daemon._connection() as conn:
                    active = conn.execute(
                        "SELECT active FROM agent_poll_state "
                        "WHERE session_id = ? AND sequence = 2",
                        (registered.session_id,),
                    ).fetchone()
                if active is not None and bool(active[0]):
                    break
                sleep(0.01)
            else:
                pytest.fail("live work poll did not become active")
            with pytest.raises(QueueConflictError, match="already active"):
                _view(daemon).wait_for_work(
                    registered.session_id,
                    "availability-1",
                    sequence=2,
                    wait_timeout_ms=1_000,
                )
            with pytest.raises(QueueConflictError, match="already active"):
                _view(daemon).wait_for_work(
                    registered.session_id,
                    "availability-1",
                    sequence=3,
                    wait_timeout_ms=10,
                )
            with pytest.raises(QueueConflictError, match="active poll"):
                _view(daemon).publish_offer(
                    _offer(registered.session_id, registered.coordinator_epoch),
                    idempotency_key="offer-during-poll",
                )
            daemon.replace_agent_policy(AgentPolicyConfig(revision="policy-2"))
            with pytest.raises(QueueServiceError, match="not authorized"):
                pending.result(timeout=2)
    finally:
        daemon.stop()


def test_poll_sequence_rejects_stale_and_gap_and_keeps_one_replay_row(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        _view(daemon).publish_offer(
            _offer(registered.session_id, registered.coordinator_epoch),
            idempotency_key="offer-1",
        )
        for sequence in (1, 2):
            assert (
                _view(daemon).wait_for_work(
                    registered.session_id,
                    registered.availability_revision,
                    sequence=sequence,
                    wait_timeout_ms=5,
                )["sequence"]
                == sequence
            )
        with pytest.raises(AgentStalePollError, match="stale"):
            _view(daemon).wait_for_work(
                registered.session_id,
                registered.availability_revision,
                sequence=1,
                wait_timeout_ms=5,
            )
        with pytest.raises(AgentPollSequenceGapError, match="gap"):
            _view(daemon).wait_for_work(
                registered.session_id,
                registered.availability_revision,
                sequence=4,
                wait_timeout_ms=5,
            )
        with daemon._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*), sequence FROM agent_poll_state "
                "WHERE principal_id = ? AND session_id = ?",
                ("principal-a", registered.session_id),
            ).fetchone()
        assert row is not None
        assert (int(row[0]), int(row[1])) == (1, 2)
    finally:
        daemon.stop()


def test_poll_identity_and_cleanup_are_scoped_to_the_principal(tmp_path: Path) -> None:
    policy = AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                "agent-a", "principal-a", "agent-a", ("default",), ("python",)
            ),
            AgentPrincipalPolicy(
                "agent-b", "principal-b", "agent-b", ("default",), ("python",)
            ),
        )
    )
    config = _config(tmp_path, policy)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        view_a = daemon.agent_view(
            LocalDaemonPrincipal("principal-a", LocalDaemonRole.AGENT, "agent-a")
        )
        view_b = daemon.agent_view(
            LocalDaemonPrincipal("principal-b", LocalDaemonRole.AGENT, "agent-b")
        )
        handshake = view_a.handshake()

        def register(view, *, key: str, agent_root_id: str, verifier_seed: str):
            return view.register(
                AgentRegistration(
                    idempotency_key=key,
                    coordinator_id=str(handshake["coordinator_id"]),
                    coordinator_epoch=str(handshake["coordinator_epoch"]),
                    agent_root_id=agent_root_id,
                    config_revision="config-1",
                    inventory_revision="inventory-1",
                    availability_revision="availability-1",
                    declared_pools=("default",),
                    declared_capabilities=("python",),
                    retirement_verifier=hashlib.sha256(
                        bytes.fromhex(verifier_seed * 32)
                    ).hexdigest(),
                )
            )

        session_a = register(
            view_a, key="register-a", agent_root_id="agent-root-a", verifier_seed="03"
        )
        session_b = register(
            view_b, key="register-b", agent_root_id="agent-root-b", verifier_seed="04"
        )
        view_a.publish_offer(
            _offer(session_a.session_id, session_a.coordinator_epoch),
            idempotency_key="offer-a",
        )
        view_b.publish_offer(
            _offer(session_b.session_id, session_b.coordinator_epoch),
            idempotency_key="offer-b",
        )
        with ThreadPoolExecutor(max_workers=1) as workers:
            held = workers.submit(
                view_a.wait_for_work,
                session_a.session_id,
                session_a.availability_revision,
                sequence=1,
                wait_timeout_ms=500,
            )
            deadline = monotonic() + 2
            while monotonic() < deadline:
                with daemon._connection() as conn:
                    active = conn.execute(
                        "SELECT active FROM agent_poll_state WHERE principal_id = ? "
                        "AND session_id = ? AND sequence = 1",
                        ("principal-a", session_a.session_id),
                    ).fetchone()
                if active is not None and bool(active[0]):
                    break
                sleep(0.01)
            else:
                pytest.fail("principal A poll did not become active")

            assert (
                view_b.wait_for_work(
                    session_b.session_id,
                    session_b.availability_revision,
                    sequence=1,
                    wait_timeout_ms=10,
                )["result"]
                == "wait"
            )
            with pytest.raises(QueueServiceError, match="not authorized"):
                view_b.wait_for_work(
                    session_a.session_id,
                    session_a.availability_revision,
                    sequence=1,
                    wait_timeout_ms=10,
                )
            with daemon._connection() as conn:
                assert conn.execute(
                    "SELECT active FROM agent_poll_state WHERE principal_id = ? "
                    "AND session_id = ? AND sequence = 1",
                    ("principal-a", session_a.session_id),
                ).fetchone()[0]
            assert held.result(timeout=2)["result"] == "wait"

        with daemon._connection() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_poll_state WHERE sequence = 1",
                ).fetchone()[0]
                == 2
            )
    finally:
        daemon.stop()


def test_reconciliation_and_offer_preserve_the_durable_effective_scope(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        with pytest.raises(QueueConflictError, match="reconciliation facts"):
            _view(daemon).reconcile(
                replace(registered, inventory_revision="different"),
                registered.coordinator_epoch,
                idempotency_key="reconcile-stale",
            )
        with pytest.raises(QueueConflictError, match="effective scope"):
            _view(daemon).publish_offer(
                replace(
                    _offer(registered.session_id, registered.coordinator_epoch),
                    pools=("other",),
                ),
                idempotency_key="offer-1",
            )
    finally:
        daemon.stop()


@pytest.mark.parametrize("old_version", [1, 2, 3, 4, 5, 6])
def test_old_roots_are_rejected_by_the_hard_cutover(
    tmp_path: Path, old_version: int
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    for path in (config.control_database, config.agent_root / "control.sqlite"):
        with sqlite3.connect(path) as conn:
            conn.execute(f"PRAGMA user_version = {old_version}")
            conn.commit()
    with pytest.raises(QueueStorageError, match="fresh roots are required"):
        LocalDaemon(config).start()
    for path in (config.control_database, config.agent_root / "control.sqlite"):
        with sqlite3.connect(path) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == old_version


def test_current_version_incomplete_session_schema_is_rejected_not_repaired(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    with sqlite3.connect(config.control_database) as conn:
        conn.execute("DROP TABLE agent_retirement_proofs")
        conn.commit()

    daemon = LocalDaemon(config)
    with pytest.raises(QueueServiceError, match="schema is incomplete"):
        daemon.start()
    with sqlite3.connect(config.control_database) as conn:
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'agent_retirement_proofs'"
            ).fetchone()
            is None
        )

    trigger_config = _config(tmp_path / "missing-trigger")
    LocalDaemon.initialize(trigger_config)
    with sqlite3.connect(trigger_config.agent_root / "control.sqlite") as conn:
        conn.execute("DROP TRIGGER agent_reference_revision_update")
        conn.commit()
    with pytest.raises(QueueServiceError, match="schema is incomplete"):
        LocalDaemon(trigger_config).start()


def test_unmerged_candidate_poll_schema_is_rejected_untouched(tmp_path: Path) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    with sqlite3.connect(config.control_database) as conn:
        conn.execute("DROP TABLE agent_poll_state")
        conn.execute(
            "CREATE TABLE agent_polls (poll_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, session_id TEXT NOT NULL, availability_revision TEXT NOT NULL, coordinator_epoch TEXT NOT NULL, wait_timeout_ms INTEGER NOT NULL, digest TEXT NOT NULL, active INTEGER NOT NULL, result_json TEXT)"
        )
        conn.commit()

    with pytest.raises(QueueServiceError, match="schema is incomplete"):
        LocalDaemon(config).start()
    with sqlite3.connect(config.control_database) as conn:
        primary_key = {
            int(row[5]): str(row[1])
            for row in conn.execute("PRAGMA table_info(agent_polls)")
            if int(row[5])
        }
    assert primary_key == {1: "poll_id"}


def test_every_agent_operation_is_causally_outside_execution_owners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        execution = daemon._execution
        assert execution is not None

        def unexpected_launch(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("agent operation reached the execution launcher")

        monkeypatch.setattr(type(execution), "_execute", unexpected_launch)
        monkeypatch.setattr(SQLitePerRunAuthorityStore, "__init__", unexpected_launch)
        execution_before = _sqlite_snapshot(config.execution_database)
        provider_before = _sqlite_snapshot(config.agent_journal)
        artifacts_before = _file_snapshot(config.run_store_root)

        _view(daemon).handshake()
        registered = _register(daemon)
        reconciled = _view(daemon).reconcile(
            registered,
            registered.coordinator_epoch,
            idempotency_key="reconcile-no-launch",
        )
        _view(daemon).publish_offer(
            _offer(reconciled.session_id, reconciled.coordinator_epoch),
            idempotency_key="offer-no-launch",
        )
        _view(daemon).wait_for_work(
            reconciled.session_id,
            reconciled.availability_revision,
            sequence=1,
            wait_timeout_ms=5,
        )
        _view(daemon).retire_clean(
            _proof(reconciled), idempotency_key="retire-no-launch"
        )

        assert _sqlite_snapshot(config.execution_database) == execution_before
        assert _sqlite_snapshot(config.agent_journal) == provider_before
        assert _file_snapshot(config.run_store_root) == artifacts_before
    finally:
        daemon.stop()
