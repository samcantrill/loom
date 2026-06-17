"""Internal argv shorthand parsing for config composition helpers."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from .errors import ConfigErrorContext, ConfigValidationError, OverrideParseError
from .overrides import parse_overrides
from .plain import PlainData, ensure_plain_data
from .provenance import ParsedOverride

ArgvValueOperation = Literal["update", "add"]
ScopedOverlayOperation = Literal["update", "add"]
ScopedOverlayCandidateOrigin = Literal["absolute", "scope_directory", "base_directory"]


@dataclass(frozen=True, slots=True)
class ArgvValueOverride:
    raw: str
    path: str
    operation: ArgvValueOperation
    value: PlainData
    order: int

    def __post_init__(self) -> None:
        if not self.raw:
            raise ConfigValidationError("ArgvValueOverride.raw must be non-empty")
        if not self.path:
            raise ConfigValidationError("ArgvValueOverride.path must be non-empty")
        if self.operation not in {"update", "add"}:
            raise ConfigValidationError(f"Unsupported value override operation: {self.operation!r}")
        if self.order < 0:
            raise ConfigValidationError("ArgvValueOverride.order must be non-negative")

        plain_value = ensure_plain_data(self.value, path=f"ArgvValueOverride[{self.order}].value")
        object.__setattr__(self, "value", plain_value)

    @classmethod
    def from_parsed_override(cls, override: ParsedOverride, *, order: int) -> "ArgvValueOverride":
        return cls(
            raw=override.raw,
            path=override.path,
            operation=override.operation,
            value=override.value,
            order=order,
        )

    def to_parsed_override(self) -> ParsedOverride:
        return ParsedOverride(
            raw=self.raw,
            path=self.path,
            operation=self.operation,
            value=self.value,
            order=self.order,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "raw": self.raw,
            "path": self.path,
            "operation": self.operation,
            "value": self.value,
            "order": self.order,
        }


@dataclass(frozen=True, slots=True)
class ScopedOverlayCandidate:
    path: str
    origin: ScopedOverlayCandidateOrigin
    exists: bool

    def __post_init__(self) -> None:
        if not self.path:
            raise ConfigValidationError("ScopedOverlayCandidate.path must be non-empty")
        if self.origin not in {"absolute", "scope_directory", "base_directory"}:
            raise ConfigValidationError(f"Unsupported scoped overlay candidate origin: {self.origin!r}")
        if not isinstance(self.exists, bool):
            raise ConfigValidationError("ScopedOverlayCandidate.exists must be a bool")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "path": self.path,
            "origin": self.origin,
            "exists": self.exists,
        }


@dataclass(frozen=True, slots=True)
class ArgvScopedOverlay:
    raw: str
    scope_path: tuple[str, ...]
    operation: ScopedOverlayOperation
    rhs: str
    candidates: tuple[ScopedOverlayCandidate, ...]
    resolved_path: str | None
    order: int

    def __post_init__(self) -> None:
        if not self.raw:
            raise ConfigValidationError("ArgvScopedOverlay.raw must be non-empty")
        if not self.scope_path:
            raise ConfigValidationError("ArgvScopedOverlay.scope_path must be non-empty")
        if any(not isinstance(segment, str) or not segment for segment in self.scope_path):
            raise ConfigValidationError("ArgvScopedOverlay.scope_path segments must be non-empty strings")
        if self.operation not in {"update", "add"}:
            raise ConfigValidationError(f"Unsupported scoped overlay operation: {self.operation!r}")
        if not self.rhs:
            raise ConfigValidationError("ArgvScopedOverlay.rhs must be non-empty")
        if self.order < 0:
            raise ConfigValidationError("ArgvScopedOverlay.order must be non-negative")

        object.__setattr__(self, "scope_path", tuple(self.scope_path))
        object.__setattr__(self, "candidates", tuple(self.candidates))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "raw": self.raw,
            "scope_path": list(self.scope_path),
            "operation": self.operation,
            "rhs": self.rhs,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "resolved_path": self.resolved_path,
            "order": self.order,
        }


@dataclass(frozen=True, slots=True)
class ArgvUnparsedArg:
    raw: str
    order: int

    def __post_init__(self) -> None:
        if not self.raw:
            raise ConfigValidationError("ArgvUnparsedArg.raw must be non-empty")
        if self.order < 0:
            raise ConfigValidationError("ArgvUnparsedArg.order must be non-negative")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "raw": self.raw,
            "order": self.order,
        }


@dataclass(frozen=True, slots=True)
class ParsedConfigArgv:
    command: str
    base_config_path: str
    value_overrides: tuple[ArgvValueOverride, ...]
    scoped_overlays: tuple[ArgvScopedOverlay, ...]
    unparsed_args: tuple[ArgvUnparsedArg, ...]

    def __post_init__(self) -> None:
        if not self.command:
            raise ConfigValidationError("ParsedConfigArgv.command must be non-empty")
        if not self.base_config_path:
            raise ConfigValidationError("ParsedConfigArgv.base_config_path must be non-empty")

        object.__setattr__(self, "value_overrides", tuple(self.value_overrides))
        object.__setattr__(self, "scoped_overlays", tuple(self.scoped_overlays))
        object.__setattr__(self, "unparsed_args", tuple(self.unparsed_args))

    @property
    def override_strings(self) -> tuple[str, ...]:
        return tuple(override.raw for override in self.value_overrides)

    @property
    def unparsed_arg_strings(self) -> tuple[str, ...]:
        return tuple(arg.raw for arg in self.unparsed_args)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "command": self.command,
            "base_config_path": self.base_config_path,
            "value_overrides": [override.to_dict() for override in self.value_overrides],
            "scoped_overlays": [overlay.to_dict() for overlay in self.scoped_overlays],
            "unparsed_args": [arg.to_dict() for arg in self.unparsed_args],
        }


def parse_config_argv(
    argv: Sequence[str],
    *,
    command_choices: Collection[str] | None = None,
    allow_unparsed: bool = False,
) -> ParsedConfigArgv:
    """Parse project CLI argv shorthand into config composition records."""

    tokens = _normalize_argv(argv)
    choices = _normalize_command_choices(command_choices)
    if not isinstance(allow_unparsed, bool):
        raise _argv_error(
            "allow_unparsed must be a bool",
            code="invalid_allow_unparsed",
            order=-1,
            details={"actual_type": type(allow_unparsed).__name__},
        )

    if not tokens:
        raise _argv_error("Missing command token in argv", code="missing_argv_command", order=0)
    command = tokens[0]
    if choices is not None and command not in choices:
        raise _argv_error(
            f"Unknown command in argv: {command!r}",
            code="unknown_command",
            order=0,
            actual=command,
            expected=list(choices),
            details={"command": command, "command_choices": list(choices)},
        )

    if len(tokens) < 2:
        raise _argv_error(
            "Missing base config path token in argv",
            code="missing_base_config_path",
            order=1,
            details={"command": command},
        )
    base_config_path = tokens[1]
    if base_config_path == "":
        raise _argv_error(
            "Base config path token must be non-empty",
            code="empty_base_config_path",
            order=1,
            details={"command": command},
        )

    value_overrides: list[ArgvValueOverride] = []
    scoped_overlays: list[ArgvScopedOverlay] = []
    unparsed_args: list[ArgvUnparsedArg] = []

    for order, token in enumerate(tokens[2:], start=2):
        if token.startswith("-"):
            unparsed_args.append(ArgvUnparsedArg(raw=token, order=order))
            continue
        if "=" not in token:
            raise _argv_error(
                f"Invalid argv config token at order {order}: {token!r}",
                code="malformed_argv_token",
                order=order,
                details={"token": token},
            )

        lhs, rhs = token.split("=", 1)
        lhs = lhs.strip()
        if "/" in lhs:
            scoped_overlays.append(
                _parse_scoped_overlay_token(
                    raw=token,
                    lhs=lhs,
                    rhs=rhs,
                    order=order,
                    base_config_path=base_config_path,
                )
            )
            continue

        try:
            parsed_override = parse_overrides((token,))[0]
        except OverrideParseError as exc:
            raise _argv_error(
                f"Invalid value override token at order {order}: {token!r}",
                code="invalid_value_override",
                order=order,
                details={"token": token, "error": str(exc)},
            ) from exc
        value_overrides.append(ArgvValueOverride.from_parsed_override(parsed_override, order=order))

    if unparsed_args and not allow_unparsed:
        raise _argv_error(
            "Unparsed command args are not allowed",
            code="disallowed_unparsed_args",
            order=unparsed_args[0].order,
            details={
                "unparsed_args": [arg.raw for arg in unparsed_args],
                "unparsed_arg_orders": [arg.order for arg in unparsed_args],
            },
        )

    return ParsedConfigArgv(
        command=command,
        base_config_path=base_config_path,
        value_overrides=tuple(value_overrides),
        scoped_overlays=tuple(scoped_overlays),
        unparsed_args=tuple(unparsed_args),
    )


def _normalize_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if isinstance(argv, str):
        raise _argv_error(
            "argv must be a sequence of strings, not one string",
            code="invalid_argv",
            order=-1,
            details={"actual_type": "str"},
        )

    tokens = tuple(argv)
    for order, token in enumerate(tokens):
        if not isinstance(token, str):
            raise _argv_error(
                f"argv token at order {order} must be text",
                code="invalid_argv_token_type",
                order=order,
                actual=type(token).__name__,
                expected="str",
                details={"actual_type": type(token).__name__},
            )
    return tokens


def _normalize_command_choices(command_choices: Collection[str] | None) -> tuple[str, ...] | None:
    if command_choices is None:
        return None
    if isinstance(command_choices, str):
        raise _argv_error(
            "command_choices must be a collection of command strings",
            code="invalid_command_choices",
            order=-1,
            details={"actual_type": "str"},
        )

    choices = tuple(command_choices)
    for index, command in enumerate(choices):
        if not isinstance(command, str) or command == "":
            raise _argv_error(
                "command_choices entries must be non-empty strings",
                code="invalid_command_choice",
                order=-1,
                details={"choice_index": index, "actual": repr(command)},
            )
    return tuple(sorted(choices))


def _parse_scoped_overlay_token(
    *,
    raw: str,
    lhs: str,
    rhs: str,
    order: int,
    base_config_path: str,
) -> ArgvScopedOverlay:
    if not lhs.endswith("/"):
        raise _argv_error(
            f"Scoped overlay token must end its left-hand side with '/': {raw!r}",
            code="invalid_scoped_overlay_marker",
            order=order,
            details={"token": raw, "lhs": lhs},
        )
    if not rhs:
        raise _argv_error(
            f"Scoped overlay token has empty RHS: {raw!r}",
            code="missing_scoped_overlay_rhs",
            order=order,
            details={"token": raw, "lhs": lhs},
        )

    operation: ScopedOverlayOperation = "update"
    scope_expression = lhs[:-1]
    if scope_expression.startswith("+"):
        operation = "add"
        scope_expression = scope_expression[1:]

    if scope_expression == "":
        raise _argv_error(
            "Root scoped overlays are not supported",
            code="unsupported_root_overlay",
            order=order,
            details={"token": raw, "lhs": lhs, "rhs": rhs},
        )

    scope_path = tuple(scope_expression.split("/"))
    invalid_segment = next(
        (
            segment
            for segment in scope_path
            if segment == "" or segment == "." or segment == ".."
        ),
        None,
    )
    if invalid_segment is not None:
        raise _argv_error(
            f"Invalid scoped overlay path in token: {raw!r}",
            code="invalid_scoped_overlay_scope",
            order=order,
            details={"token": raw, "scope_path": list(scope_path), "invalid_segment": invalid_segment},
        )

    candidates = _resolve_scoped_overlay_candidates(
        base_config_path=base_config_path,
        scope_path=scope_path,
        rhs=rhs,
    )
    resolved_path = next((candidate.path for candidate in candidates if candidate.exists), None)
    if resolved_path is None:
        raise _argv_error(
            f"Could not resolve scoped overlay source for token: {raw!r}",
            code="missing_scoped_overlay_source",
            order=order,
            details={
                "token": raw,
                "scope_path": list(scope_path),
                "rhs": rhs,
                "candidate_paths": [candidate.path for candidate in candidates],
            },
        )

    return ArgvScopedOverlay(
        raw=raw,
        scope_path=scope_path,
        operation=operation,
        rhs=rhs,
        candidates=candidates,
        resolved_path=resolved_path,
        order=order,
    )


def _resolve_scoped_overlay_candidates(
    *,
    base_config_path: str,
    scope_path: tuple[str, ...],
    rhs: str,
) -> tuple[ScopedOverlayCandidate, ...]:
    rhs_path = Path(rhs)
    if rhs_path.is_absolute():
        path = _normalize_path(rhs_path)
        return (
            ScopedOverlayCandidate(
                path=str(path),
                origin="absolute",
                exists=path.is_file(),
            ),
        )

    base_dir = _normalize_path(Path(base_config_path).parent)
    scope_dir = _normalize_path(base_dir.joinpath(*scope_path))
    variants = _relative_rhs_variants(rhs_path)

    candidates: list[ScopedOverlayCandidate] = []
    for origin, root in (("scope_directory", scope_dir), ("base_directory", base_dir)):
        for variant in variants:
            path = _normalize_path(root / variant)
            candidates.append(
                ScopedOverlayCandidate(
                    path=str(path),
                    origin=cast(ScopedOverlayCandidateOrigin, origin),
                    exists=path.is_file(),
                )
            )
    return tuple(candidates)


def _relative_rhs_variants(rhs_path: Path) -> tuple[Path, ...]:
    if rhs_path.suffix != "":
        return (rhs_path,)

    try:
        return (rhs_path.with_suffix(".yaml"), rhs_path.with_suffix(".yml"))
    except ValueError:
        return (rhs_path,)


def _normalize_path(path: Path) -> Path:
    return path.resolve(strict=False)


def _argv_error(
    message: str,
    *,
    code: str,
    order: int,
    expected: PlainData | None = None,
    actual: PlainData | None = None,
    details: dict[str, PlainData] | None = None,
) -> ConfigValidationError:
    return ConfigValidationError(
        message,
        context=ConfigErrorContext(
            code=code,
            source_kind="argv",
            source_order=order,
            source_path="<argv>",
            expected=expected,
            actual=actual,
            directive="argv_config_shorthand",
            remediation=_argv_remediation(code),
            details=details,
        ),
    )


def _argv_remediation(code: str) -> str | None:
    if code == "missing_argv_command":
        return "Pass argv as '<command> <base-config> ...'."
    if code == "missing_base_config_path":
        return "Pass a base config path immediately after the command token."
    if code == "unknown_command":
        return "Choose one of the command choices supplied by the caller."
    if code == "disallowed_unparsed_args":
        return "Pass allow_unparsed=True when command-specific args should be returned to the caller."
    if code == "malformed_argv_token":
        return "Use key=value for value overrides, scope/=target for scoped overlays, or -prefixed command args."
    if code == "invalid_value_override":
        return "Use existing value override syntax for no-slash argv tokens."
    if code == "invalid_scoped_overlay_marker":
        return "Use a trailing slash before '=' for scoped overlays, for example 'model/=variant'."
    if code == "unsupported_root_overlay":
        return "Use the base config path to choose the root config; scoped overlays must target a non-root scope."
    if code == "missing_scoped_overlay_source":
        return "Provide an existing scoped overlay file or an RHS that resolves through the documented lookup order."
    return None


__all__ = [
    "ArgvScopedOverlay",
    "ArgvUnparsedArg",
    "ArgvValueOverride",
    "ParsedConfigArgv",
    "ScopedOverlayCandidate",
    "parse_config_argv",
]
