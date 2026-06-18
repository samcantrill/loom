"""Unit tests for protocol definitions."""

from loom.protocols import Fingerprintable, Validatable


class _Both:
    def validate(self) -> None:
        return None

    def fingerprint(self) -> str:
        return "ok"


class _ValidateOnly:
    def validate(self) -> None:
        return None


def test_protocol_contract_names_exist() -> None:
    assert Validatable
    assert Fingerprintable


def test_protocols_are_structural_contracts() -> None:
    candidate = _Both()
    assert callable(candidate.validate)
    assert callable(candidate.fingerprint)


def test_incomplete_object_lacks_fingerprint_shape() -> None:
    candidate = _ValidateOnly()
    assert callable(candidate.validate)
    assert not hasattr(candidate, "fingerprint")
