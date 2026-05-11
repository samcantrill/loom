"""Contract tests for private repository compatibility failures."""

from __future__ import annotations

import pytest

from loom.authority._repository import (
    AuthorityRepositoryCompatibilityFailure,
    AuthorityRepositoryCompatibilityKind,
)
from loom.pipeline.stores import (
    AuthorityProtocolErrorCategory,
    AuthorityProtocolRejection,
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
