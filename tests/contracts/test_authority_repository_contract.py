"""Contract tests for private repository compatibility failures."""

from __future__ import annotations

import pytest

from loom.pipeline.status import RunStatus
from loom.authority._repository import (
    AuthorityRepositoryError,
    AuthorityRepositoryCompatibilityFailure,
    AuthorityRepositoryCompatibilityKind,
    initialize_authority_repository,
)
from loom.pipeline.stores import (
    AuthorityProtocolErrorCategory,
    AuthorityProtocolRejection,
    BackendRevision,
)


pytestmark = pytest.mark.contract


_PROTOCOL_CATEGORY_BY_FAILURE = {
    AuthorityRepositoryCompatibilityKind.MISSING: (
        AuthorityProtocolErrorCategory.UNAVAILABLE_SERVICE
    ),
    AuthorityRepositoryCompatibilityKind.UNSUPPORTED_OLDER: (
        AuthorityProtocolErrorCategory.VALIDATION
    ),
    AuthorityRepositoryCompatibilityKind.UNSUPPORTED_NEWER: (
        AuthorityProtocolErrorCategory.VALIDATION
    ),
    AuthorityRepositoryCompatibilityKind.CORRUPT: (
        AuthorityProtocolErrorCategory.VALIDATION
    ),
}


@pytest.mark.parametrize("kind", tuple(AuthorityRepositoryCompatibilityKind))
def test_repository_compatibility_failures_map_to_protocol_rejections(
    kind: AuthorityRepositoryCompatibilityKind,
) -> None:
    failure = AuthorityRepositoryCompatibilityFailure(
        kind=kind,
        message=f"{kind.value} repository",
        found_version=2
        if kind is AuthorityRepositoryCompatibilityKind.UNSUPPORTED_NEWER
        else None,
    )

    rejection = AuthorityProtocolRejection(
        category=_PROTOCOL_CATEGORY_BY_FAILURE[kind],
        code=failure.code,
        message=failure.message,
        detail=failure.to_dict(),
    )

    assert rejection.code == f"authority_repository_{kind.value}"
    assert rejection.detail["kind"] == kind.value
    assert rejection.to_dict()["category"] == _PROTOCOL_CATEGORY_BY_FAILURE[kind].value


def test_repository_stale_revision_maps_to_protocol_rejection(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )
    run_uri = "file:///runs/contract-r1"
    initial = repository.admit_run(run_uri)
    repository.transition_run(
        run_uri,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.RUNNING,
        expected_revision=initial,
    )

    with pytest.raises(AuthorityRepositoryError) as exc_info:
        repository.transition_run(
            run_uri,
            from_status=RunStatus.RUNNING,
            to_status=RunStatus.SUCCEEDED,
            expected_revision=initial,
        )

    rejection = AuthorityProtocolRejection(
        category=AuthorityProtocolErrorCategory.STALE_REVISION,
        code="authority_repository_stale_revision",
        message=str(exc_info.value),
        detail={"run_uri": run_uri, "expected_revision": initial.to_dict()},
    )

    assert rejection.category is AuthorityProtocolErrorCategory.STALE_REVISION
    assert rejection.message == "stale run revision"


def test_repository_stale_fencing_maps_to_protocol_rejection(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )
    run_uri = "file:///runs/contract-r1"
    revision = repository.admit_run(run_uri)
    lease = repository.acquire_controller_lease(
        run_uri,
        owner_id="controller-1",
        lease_ttl_seconds=30,
        expected_revision=revision,
    )

    with pytest.raises(AuthorityRepositoryError) as exc_info:
        repository.renew_controller_lease(
            run_uri,
            lease.lease_id,
            owner_id="controller-1",
            fencing_token="wrong-fence",
            lease_ttl_seconds=30,
            expected_revision=BackendRevision(
                sequence=lease.revision.sequence,
                token=lease.revision.token,
                created_at=lease.revision.created_at,
            ),
        )

    rejection = AuthorityProtocolRejection(
        category=AuthorityProtocolErrorCategory.STALE_FENCING,
        code="authority_repository_stale_fencing",
        message=str(exc_info.value),
        detail={"run_uri": run_uri, "lease_id": lease.lease_id},
    )

    assert rejection.category is AuthorityProtocolErrorCategory.STALE_FENCING
    assert rejection.message == "stale or foreign fencing token"
