"""Plain immutable result values for opt-in extension conformance checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loom.serialization import PlainData


@dataclass(frozen=True, slots=True)
class ContractFinding:
    """One deterministic conformance observation."""

    code: str
    status: Literal["pass", "fail"]
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("ContractFinding.code must be a non-empty string")
        if self.status not in {"pass", "fail"}:
            raise ValueError("ContractFinding.status must be pass or fail")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("ContractFinding.message must be a non-empty string")

    def to_dict(self) -> dict[str, PlainData]:
        return {"code": self.code, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class ContractReport:
    """Immutable, plain-data report from one versioned contract checker."""

    contract: str
    contract_version: int
    findings: tuple[ContractFinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.contract, str) or not self.contract:
            raise ValueError("ContractReport.contract must be a non-empty string")
        if (
            not isinstance(self.contract_version, int)
            or isinstance(self.contract_version, bool)
            or self.contract_version <= 0
        ):
            raise ValueError(
                "ContractReport.contract_version must be a positive integer"
            )
        findings = tuple(self.findings)
        if not all(isinstance(finding, ContractFinding) for finding in findings):
            raise TypeError(
                "ContractReport.findings must contain ContractFinding values"
            )
        object.__setattr__(self, "findings", findings)

    @property
    def ok(self) -> bool:
        return all(finding.status == "pass" for finding in self.findings)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "contract": self.contract,
            "contract_version": self.contract_version,
            "findings": [finding.to_dict() for finding in self.findings],
            "ok": self.ok,
        }

    def raise_for_errors(self) -> None:
        """Raise ``AssertionError`` when one or more checks failed."""

        failures = tuple(
            finding for finding in self.findings if finding.status == "fail"
        )
        if failures:
            summary = "; ".join(
                f"{finding.code}: {finding.message}" for finding in failures
            )
            raise AssertionError(summary)
