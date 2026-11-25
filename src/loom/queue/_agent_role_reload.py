"""Prepare and durably bind trusted resident role reloads."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._agent_session_journal import (
    _RemoteAgentJournal, _agent_active_fingerprint, _agent_config_revision,
    _agent_inventory_revision, _agent_revision, _resident_profile_key,
)
from .agent_sessions import AgentControl, AgentControlEffect
from .errors import QueueConflictError, QueueServiceError

if TYPE_CHECKING:
    from ._remote_stage_execution import ResidentExecutionProfile
    from .agent_session_transport import AgentTlsClientConfig


@dataclass(frozen=True, slots=True)
class PreparedAgentReload:
    """One fully validated owner-local reload plan awaiting durable activation."""

    replacement: AgentTlsClientConfig
    profiles: Mapping[str, ResidentExecutionProfile]
    retained_profiles: Mapping[str, ResidentExecutionProfile]
    retained: bool
    install_role: Callable[[], None]
    config_revision: str
    inventory_revision: str
    active_fingerprint: str

    def commit(self, journal: _RemoteAgentJournal, control: AgentControl) -> AgentControlEffect:
        journal.bind_reload_intent(control, self.active_fingerprint)
        effect = AgentControlEffect(
            operation_id=control.operation_id,
            code="applied",
            config_revision=self.config_revision,
            inventory_revision=self.inventory_revision,
            availability_revision=_agent_revision(
                "availability",
                {
                    "operation_id": control.operation_id,
                    "drained": True,
                    "inventory_revision": self.inventory_revision,
                },
            ),
        )
        journal.complete_reload(control, self.replacement, effect)
        return effect


@dataclass(frozen=True, slots=True)
class AgentRoleReload:
    """Current role bindings against which a trusted replacement must qualify."""

    current: AgentTlsClientConfig
    profiles: Mapping[str, ResidentExecutionProfile]
    retained_profiles: Mapping[str, ResidentExecutionProfile]
    slurm_enabled: bool

    def prepare(
        self,
        replacement: AgentTlsClientConfig,
        *,
        retained: bool,
        prepare_install: Callable[[AgentTlsClientConfig], Callable[[], None]] | None,
    ) -> PreparedAgentReload:
        self.validate(replacement, retained_work=retained)
        next_profiles = {
            item.descriptor.profile_id: item for item in replacement.resident_profiles
        }
        next_retained_profiles = dict(self.retained_profiles)
        if retained:
            next_retained_profiles.update(
                {_resident_profile_key(item): item for item in self.profiles.values()}
            )

        def install_role() -> None:
            return

        if prepare_install is not None:
            install_role = prepare_install(replacement)
            if not callable(install_role):
                raise QueueServiceError("trusted agent role reload plan is unavailable")
        return PreparedAgentReload(
            replacement=replacement,
            profiles=next_profiles,
            retained_profiles=next_retained_profiles,
            retained=retained,
            install_role=install_role,
            config_revision=_agent_config_revision(replacement),
            inventory_revision=_agent_inventory_revision(replacement),
            active_fingerprint=_agent_active_fingerprint(replacement),
        )

    def validate(
        self,
        replacement: AgentTlsClientConfig,
        *,
        retained_work: bool,
    ) -> None:
        if (
            replacement.deployment_configuration_fingerprint
            != self.current.deployment_configuration_fingerprint
        ):
            raise QueueConflictError(
                "agent reload cannot replace immutable role configuration"
            )
        if (
            replacement.agent_root != self.current.agent_root
            or replacement.url != self.current.url
            or replacement.server_ca_path != self.current.server_ca_path
            or replacement.certificate_path != self.current.certificate_path
            or replacement.private_key_path != self.current.private_key_path
        ):
            raise QueueServiceError(
                "agent reload cannot replace its live transport or owner root"
            )
        if replacement.slurm_profiles and not self.slurm_enabled:
            raise QueueConflictError(
                "installing SLURM submission requires fresh agent-root initialization"
            )
        if (
            _resident_launch_profile_set(replacement) != _resident_launch_profile_set(self.current)
            or replacement.container_policies != self.current.container_policies
        ):
            raise QueueConflictError(
                "agent reload requires fresh agent-root initialization for "
                "resident profile set"
            )
        if (
            retained_work
            and _agent_active_fingerprint(replacement) != _agent_active_fingerprint(self.current)
            and not self._slurm_transport_only_reload(replacement)
        ):
            raise QueueConflictError(
                "agent reload cannot replace active configuration with retained work"
            )
        existing = (*self.profiles.values(), *self.retained_profiles.values())
        for candidate in replacement.resident_profiles:
            for retained in existing:
                if (
                    retained_work
                    and retained.descriptor == candidate.descriptor
                    and _resident_profile_key(retained)
                    != _resident_profile_key(candidate)
                ):
                    raise QueueConflictError(
                        "agent reload reuses a live profile identity for changed bindings"
                    )

    def _slurm_transport_only_reload(self, replacement: AgentTlsClientConfig) -> bool:
        current = self.current
        return (
            current._transport_reload_fingerprint is not None
            and current._transport_reload_fingerprint == replacement._transport_reload_fingerprint
            and current.transport_policy != replacement.transport_policy
            and tuple(profile.configuration_fingerprint for profile in current.slurm_profiles)
            == tuple(profile.configuration_fingerprint for profile in replacement.slurm_profiles)
        )


def _resident_launch_profile_set(
    config: AgentTlsClientConfig,
) -> tuple[tuple[str, str], ...]:
    """Canonical executable bindings held by the initialized supervisor.

    Capacity is intentionally absent: it contributes to provider inventory, not
    the protected worker executable, descriptor, or project binding.
    """

    return tuple(
        sorted(
            (
                profile.descriptor.profile_id,
                profile.launch_profile.fingerprint,
            )
            for profile in config.resident_profiles
        )
    )
