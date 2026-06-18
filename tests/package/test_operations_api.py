import subprocess
import sys

import pytest

from loom.operations import (
    OperationAdapterIdentity,
    OperationDiagnostic,
    OperationDiagnosticSeverity,
    OperationEvidenceCheck,
    OperationEvidenceRecord,
    OperationEvidenceStatus,
    OperationResult,
    OperationStatus,
    OperationSupport,
    OperationSupportRecord,
)


pytestmark = pytest.mark.package


def test_operations_module_exports_stable() -> None:
    import loom.operations as operations

    assert set(operations.__all__) == {
        "OperationValidationError",
        "OperationStatus",
        "OperationSupport",
        "OperationDiagnosticSeverity",
        "OperationEvidenceStatus",
        "OperationAdapterIdentity",
        "OperationDiagnostic",
        "OperationEvidenceCheck",
        "OperationEvidenceRecord",
        "OperationSupportRecord",
        "OperationResult",
    }


def test_operations_symbol_imports_are_typed() -> None:
    assert OperationStatus.SUCCEEDED
    assert OperationSupport.UNKNOWN
    assert OperationDiagnosticSeverity.ERROR
    assert OperationEvidenceStatus.PROVEN
    assert OperationAdapterIdentity(name="demo", kind="backend", version="1").name == "demo"
    assert (
        OperationDiagnostic(
            code="demo.unsupported",
            message="supported",
            severity=OperationDiagnosticSeverity.INFO,
            details={},
        ).code
        == "demo.unsupported"
    )

    unsupported = OperationResult.unsupported("test", reason="not ready")
    assert OperationResult.from_dict(unsupported.to_dict()) == unsupported

    assert OperationSupportRecord.from_dict(
        {
            "operation": "copy",
            "support": "supported",
            "message": "ok",
            "diagnostics": (
                {
                    "code": "demo.supported",
                    "message": "ok",
                    "severity": "info",
                    "details": {},
                },
            ),
            "details": {},
        }
    ) == OperationSupportRecord(
        operation="copy",
        support=OperationSupport.SUPPORTED,
        message="ok",
        diagnostics=(
            OperationDiagnostic(
                code="demo.supported",
                message="ok",
                severity=OperationDiagnosticSeverity.INFO,
                details={},
            ),
        ),
        details={},
    )

    assert OperationEvidenceRecord.from_dict(
        {
            "status": "unproven",
            "checks": (
                {
                    "name": "checksum_match",
                    "status": "proven",
                    "message": "missing",
                    "details": {},
                },
            ),
            "adapter": None,
            "details": {"reason": "manual"},
        }
    ) == OperationEvidenceRecord(
        status=OperationEvidenceStatus.UNPROVEN,
        checks=(
            OperationEvidenceCheck(
                name="checksum_match",
                status=OperationEvidenceStatus.PROVEN,
                message="missing",
                details={},
            ),
        ),
        adapter=None,
        details={"reason": "manual"},
    )


def test_operations_import_is_lightweight() -> None:
    from textwrap import dedent

    script = dedent(
        """
        import sys
        import loom.operations

        for forbidden in (
            "loom.runs",
            "loom.diagnostics",
            "loom.pipeline",
            "loom.cli",
            "loom.plugins",
            "loom.authority",
            "boto3",
            "google",
            "azure",
            "mlflow",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.operations")

        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
