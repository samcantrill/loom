"""Tests for authority configuration and capability admission."""

import pytest

from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityConfigError,
    AuthorityDeploymentProfile,
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    CapabilityScope,
    RequiredAuthorityCapability,
    authority_config_from_env,
    authority_config_to_cli_args,
    authority_config_to_env,
    admit_authority_capabilities,
)

pytestmark = pytest.mark.unit


def _capabilities(*capabilities: BackendCapability) -> BackendCapabilitySet:
    return BackendCapabilitySet(
        backend_name="unit-test-authority",
        records=tuple(
            BackendCapabilityRecord(
                capability=capability,
                scope=CapabilityScope.PER_RUN,
            )
            for capability in capabilities
        ),
    )


def test_authority_config_round_trips_and_redacts_endpoint() -> None:
    config = AuthorityConfig(
        backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
        deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
        endpoint="https://example.invalid/token-secret",
        workspace_id="workspace-1",
        state_path="/tmp/loom-authority",
        reference_id="authority-ref-1",
        metadata={"token": "secret-value", "label": "test"},
    )

    restored = AuthorityConfig.from_dict(config.to_dict())

    assert restored == config
    assert restored.to_reference().to_dict()["reference_id"] == "authority-ref-1"
    assert restored.redacted_dict()["endpoint"] == "<redacted>"
    assert restored.redacted_dict()["metadata"] == {
        "label": "test",
        "token": "<redacted>",
    }


def test_authority_config_rejects_unknown_fields() -> None:
    with pytest.raises(AuthorityConfigError, match="unknown field"):
        AuthorityConfig.from_dict({"backend_kind": "test_fake", "extra": True})


def test_authority_config_defaults_to_co_located_service() -> None:
    config = AuthorityConfig()
    restored = AuthorityConfig.from_dict({})

    assert config.backend_kind is AuthorityBackendKind.CO_LOCATED_SERVICE
    assert config.deployment_profile is AuthorityDeploymentProfile.CO_LOCATED
    assert restored.backend_kind is AuthorityBackendKind.CO_LOCATED_SERVICE
    assert restored.deployment_profile is AuthorityDeploymentProfile.CO_LOCATED


def test_authority_config_round_trips_through_environment_shape() -> None:
    config = AuthorityConfig(
        backend_kind=AuthorityBackendKind.CO_LOCATED_SERVICE,
        deployment_profile=AuthorityDeploymentProfile.CO_LOCATED,
        endpoint="tcp://127.0.0.1:12345",
        reference_id="service-fixture",
        metadata={"authkey": "secret", "label": "fixture"},
    )

    env = authority_config_to_env(config)
    restored = authority_config_from_env(env)

    assert restored == config
    assert env["LOOM_AUTHORITY_METADATA_JSON"] == (
        '{"authkey":"secret","label":"fixture"}'
    )


def test_authority_config_cli_args_use_public_worker_flags() -> None:
    config = AuthorityConfig(
        backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
        deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
        endpoint="tcp://127.0.0.1:12345",
        reference_id="managed",
        metadata={"authkey": "secret"},
    )

    args = authority_config_to_cli_args(config)

    assert args[:6] == (
        "--authority-backend",
        "managed_service",
        "--authority-profile",
        "managed_service",
        "--authority-endpoint",
        "tcp://127.0.0.1:12345",
    )
    assert "--authority-metadata-json" in args


def test_serial_run_admission_reports_missing_capability() -> None:
    config = AuthorityConfig(backend_kind=AuthorityBackendKind.TEST_FAKE)
    result = admit_authority_capabilities(
        config=config,
        capabilities=_capabilities(BackendCapability.RUN_ADMISSION),
        required=[RequiredAuthorityCapability.SERIAL_RUN],
    )

    assert not result.supported
    assert result.errors[0].code == "authority.unsupported_capability"
    assert result.errors[0].required is RequiredAuthorityCapability.SERIAL_RUN
    assert result.errors[0].backend_kind == "test_fake"
    assert result.errors[0].deployment_profile == "co_located"
    assert {
        error.capability for error in result.errors if error.capability is not None
    } == {
        BackendCapability.ATOMIC_TRANSITIONS,
        BackendCapability.REVISIONED_SNAPSHOTS,
        BackendCapability.MONOTONIC_REVISIONS,
    }


def test_live_worker_admission_rejects_deferred_profile_before_capability_checks() -> (
    None
):
    config = AuthorityConfig(
        backend_kind=AuthorityBackendKind.DEFERRED_FINALIZATION,
        deployment_profile=AuthorityDeploymentProfile.DEFERRED_FINALIZATION,
    )

    result = admit_authority_capabilities(
        config=config,
        capabilities=_capabilities(),
        required=[RequiredAuthorityCapability.SLURM_LIVE_WORKER],
    )

    assert not result.supported
    assert result.errors[0].code == "authority.unsupported_profile"
    assert "live submitted workers" in result.errors[0].message


def test_live_worker_admission_rejects_direct_database_profile() -> None:
    config = AuthorityConfig(
        backend_kind=AuthorityBackendKind.DIRECT_DATABASE,
        deployment_profile=AuthorityDeploymentProfile.DIRECT_DATABASE,
    )

    result = admit_authority_capabilities(
        config=config,
        capabilities=_capabilities(),
        required=[RequiredAuthorityCapability.SLURM_LIVE_WORKER],
    )

    assert not result.supported
    assert result.errors[0].code == "authority.unsupported_profile"
    assert result.errors[0].deployment_profile == "direct_database"
    assert "service authority" in result.errors[0].message
