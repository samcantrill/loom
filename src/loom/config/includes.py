"""Internal include target resolution helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from urllib.parse import SplitResult, unquote, urlparse

from .errors import ConfigErrorContext, ConfigIncludeResolutionError
from .provenance import ConfigSource
from .source_maps import ConfigPath, format_config_path

IncludeTargetKind = Literal["bare_name", "explicit_relative", "absolute", "file_uri"]

_INTERPOLATION_PATTERN: Final = re.compile(r"\$\{[^{}]+\}")
_BARE_NAME_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]+$")
_DOT_SEGMENTS: Final = {".", ".."}
_HEX_DIGITS: Final = "0123456789ABCDEFabcdef"


@dataclass(frozen=True, slots=True)
class IncludeResolutionResult:
    """Resolved include target metadata."""

    authored_target: str
    include_site_path: ConfigPath
    source_path: str
    resolved_path: Path
    target_kind: IncludeTargetKind
    explicit_escape: bool


def resolve_include_target(
    target: str,
    *,
    source: ConfigSource,
    include_site_path: ConfigPath,
) -> IncludeResolutionResult:
    """Resolve one authored include target to a concrete local config path."""

    _validate_include_site_path(source, include_site_path)
    source_path = _resolve_source_path(source, include_site_path)

    if not target:
        raise _include_error(
            "Include target must be non-empty.",
            code="invalid_target",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            details={"reason": "empty_target"},
        )

    if _INTERPOLATION_PATTERN.search(target):
        raise _include_error(
            "Resolver-style interpolation targets are not supported in include resolution.",
            code="resolver_dependent",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            details={"reason": "interpolation_token", "target": target},
        )

    parsed = urlparse(target)
    if parsed.scheme:
        return _resolve_uri_target(
            target=target,
            parsed=parsed,
            source=source,
            include_site_path=include_site_path,
        )

    if _BARE_NAME_PATTERN.fullmatch(target):
        return _resolve_bare_name_target(
            target=target,
            source=source,
            source_path=source_path,
            include_site_path=include_site_path,
        )

    if "\\" in target:
        raise _include_error(
            "Backslash path separators are not supported in include targets.",
            code="unsafe_relative_path",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            details={"reason": "unsupported_path_separator"},
        )

    if target.startswith((".", "./", "../")) or target.startswith("/"):
        absolute_or_relative = Path(target)
        kind: IncludeTargetKind
        if absolute_or_relative.is_absolute():
            kind = "absolute"
        else:
            kind = "explicit_relative"
        return _validate_candidate(
            target=target,
            candidate=absolute_or_relative
            if absolute_or_relative.is_absolute()
            else source_path.parent.joinpath(target),
            source=source,
            include_site_path=include_site_path,
            kind=kind,
            explicit_escape=True,
        )

    if "/" in target or Path(target).suffix:
        explicit = source_path.parent.joinpath(target)
        return _validate_candidate(
            target=target,
            candidate=explicit,
            source=source,
            include_site_path=include_site_path,
            kind="explicit_relative",
            explicit_escape=True,
        )

    raise _include_error(
        "Include target did not match any supported Phase 5 include form.",
        code="unsupported_target_form",
        source=source,
        include_site_path=include_site_path,
        authored_target=target,
        expected="bare-name token or explicit relative/absolute/file URI",
        details={"reason": "unsupported_target_form"},
    )


def _resolve_uri_target(
    *,
    target: str,
    parsed: SplitResult,
    source: ConfigSource,
    include_site_path: ConfigPath,
) -> IncludeResolutionResult:
    parsed_uri = parsed
    scheme = parsed_uri.scheme.lower()

    if scheme != "file":
        raise _include_error(
            f"Unsupported include target scheme {parsed_uri.scheme!r}.",
            code="unsupported_scheme",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            expected="relative, absolute, bare-name, or file:// path",
            details={
                "scheme": scheme,
                "reason": "unsupported_scheme",
            },
        )

    if parsed_uri.netloc not in ("", None):
        raise _include_error(
            "file URI host names are not supported in Phase 5.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            details={
                "scheme": scheme,
                "reason": "file_uri_authority",
                "authority": parsed_uri.netloc,
            },
        )

    if parsed_uri.params:
        raise _include_error(
            "file URI params are not supported in Phase 5.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            details={
                "scheme": scheme,
                "reason": "file_uri_params",
                "params": parsed_uri.params,
            },
        )

    if parsed_uri.query:
        raise _include_error(
            "file URI query strings are not supported in Phase 5.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            details={
                "scheme": scheme,
                "reason": "file_uri_query",
                "query": parsed_uri.query,
            },
        )

    if parsed_uri.fragment:
        raise _include_error(
            "file URI fragments are not supported in Phase 5.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            details={
                "scheme": scheme,
                "reason": "file_uri_fragment",
                "fragment": parsed_uri.fragment,
            },
        )

    raw_path = parsed_uri.path
    _validate_file_uri_path(
        raw_path=raw_path,
        source=source,
        include_site_path=include_site_path,
        authored_target=target,
    )
    decoded_path = unquote(raw_path)
    candidate = Path(decoded_path)

    return _validate_candidate(
        target=target,
        candidate=candidate,
        source=source,
        include_site_path=include_site_path,
        kind="file_uri",
        explicit_escape=True,
        details={
            "scheme": scheme,
            "path": raw_path,
            "decoded_path": decoded_path,
        },
    )


def _resolve_bare_name_target(
    *,
    target: str,
    source: ConfigSource,
    source_path: Path,
    include_site_path: ConfigPath,
) -> IncludeResolutionResult:
    derived_dir = source_path.parent
    for segment in include_site_path[:-1]:
        if not isinstance(segment, str):
            raise _include_error(
                "Include-site mapping segments must be strings for bare-name resolution.",
                code="invalid_include_site",
                source=source,
                include_site_path=include_site_path,
                authored_target=target,
                details={"reason": "include_site_segment_type", "segment": repr(segment)},
            )
        _validate_bare_parent_segment(
            segment=segment,
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
        )
        derived_dir = derived_dir / segment

    candidate = derived_dir / f"{target}.yaml"
    return _validate_candidate(
        target=target,
        candidate=candidate,
        source=source,
        include_site_path=include_site_path,
        kind="bare_name",
        explicit_escape=False,
        details={"derived_dir": str(derived_dir)},
    )


def _validate_candidate(
    *,
    target: str,
    candidate: Path,
    source: ConfigSource,
    include_site_path: ConfigPath,
    kind: IncludeTargetKind,
    explicit_escape: bool,
    details: dict[str, object] | None = None,
) -> IncludeResolutionResult:
    if not candidate.exists():
        raise _include_error(
            f"Include target does not resolve to an existing file: {candidate}",
            code="target_not_found",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            expected="existing regular file",
            actual="missing target",
            details={
                "candidate_path": str(candidate),
                "target_kind": kind,
                "explicit_escape": explicit_escape,
                **(details or {}),
            },
        )

    if not candidate.is_file():
        raise _include_error(
            f"Include target must resolve to a regular file: {candidate}",
            code="target_not_file",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            expected="regular file",
            actual="directory",
            details={
                "candidate_path": str(candidate),
                "target_kind": kind,
                "explicit_escape": explicit_escape,
                **(details or {}),
            },
        )

    return IncludeResolutionResult(
        authored_target=target,
        include_site_path=include_site_path,
        source_path=str(source.path),
        resolved_path=candidate,
        target_kind=kind,
        explicit_escape=explicit_escape,
    )


def _validate_include_site_path(source: ConfigSource, include_site_path: ConfigPath) -> None:
    if not include_site_path:
        raise _include_error(
            "Include-site path must be non-empty and end in _include_.",
            code="invalid_include_site",
            source=source,
            include_site_path=(),
            authored_target="",
            details={"reason": "empty_include_site"},
        )

    if include_site_path[-1] != "_include_":
        raise _include_error(
            "Include-site path must point at _include_.",
            code="invalid_include_site",
            source=source,
            include_site_path=include_site_path,
            authored_target="",
            details={
                "reason": "include_site_not_include_key",
                "observed_segment": str(include_site_path[-1]),
            },
        )

    for segment in include_site_path[:-1]:
        if not isinstance(segment, str):
            raise _include_error(
                "Include-site path may not contain index segments for bare-name resolution.",
                code="invalid_include_site",
                source=source,
                include_site_path=include_site_path,
                authored_target="",
                details={"reason": "include_site_segment_type", "segment": repr(segment)},
            )

        if segment in _DOT_SEGMENTS or not segment:
            raise _include_error(
                "Include-site segment is unsafe for include-site validation.",
                code="invalid_include_site",
                source=source,
                include_site_path=include_site_path,
                authored_target="",
                details={"reason": "unsafe_parent_segment", "segment": segment},
            )
        if "/" in segment or "\\" in segment:
            raise _include_error(
                "Include-site segment may not contain path separators.",
                code="invalid_include_site",
                source=source,
                include_site_path=include_site_path,
                authored_target="",
                details={
                    "reason": "parent_segment_contains_separator",
                    "segment": segment,
                },
            )


def _resolve_source_path(source: ConfigSource, include_site_path: ConfigPath) -> Path:
    if not source.path:
        raise _include_error(
            "Config source path must be non-empty.",
            code="invalid_source",
            source=source,
            include_site_path=include_site_path,
            authored_target="",
            details={"reason": "empty_source_path"},
        )
    source_path = Path(source.path)
    if not source_path.is_file():
        raise _include_error(
            "Config source path must reference an existing file.",
            code="invalid_source",
            source=source,
            include_site_path=include_site_path,
            authored_target="",
            details={"reason": "source_is_not_file", "source_path": source.path},
        )
    return source_path


def _validate_bare_parent_segment(
    *,
    segment: str,
    source: ConfigSource,
    include_site_path: ConfigPath,
    authored_target: str,
) -> None:
    if segment in _DOT_SEGMENTS or not segment:
        raise _include_error(
            "Include-site segment is unsafe for bare-name resolution.",
            code="unsafe_include_site",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={
                "reason": "unsafe_parent_segment",
                "segment": segment,
            },
        )
    if "/" in segment or "\\" in segment:
        raise _include_error(
            "Include-site segment contains path separators and is unsafe for bare-name resolution.",
            code="unsafe_include_site",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={
                "reason": "parent_segment_contains_separator",
                "segment": segment,
            },
        )


def _validate_file_uri_path(
    *,
    raw_path: str,
    source: ConfigSource,
    include_site_path: ConfigPath,
    authored_target: str,
) -> None:
    if not raw_path or raw_path == "/":
        raise _include_error(
            "file:// targets must reference an explicit file path.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={"scheme": "file", "path": raw_path, "reason": "empty_file_uri_path"},
        )

    if "%" in raw_path and not _is_valid_percent_encoding(raw_path):
        raise _include_error(
            "Malformed percent escape in file URI path.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={"scheme": "file", "path": raw_path, "reason": "malformed_percent_escape"},
        )

    lowered = raw_path.lower()
    if "%2f" in lowered:
        raise _include_error(
            "Escaped path separators are not supported in file URI targets.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={"scheme": "file", "path": raw_path, "reason": "escaped_path_separator"},
        )

    if "%5c" in lowered:
        raise _include_error(
            "Escaped path separators are not supported in file URI targets.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={"scheme": "file", "path": raw_path, "reason": "escaped_path_separator"},
        )

    if "%2e" in lowered:
        raise _include_error(
            "Encoded dot segments are not supported in file URI targets.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={"scheme": "file", "path": raw_path, "reason": "encoded_dot_segment"},
        )

    if not raw_path.startswith("/"):
        raise _include_error(
            "file URI must use an absolute path.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={"scheme": "file", "path": raw_path, "reason": "non_absolute_path"},
        )


def _is_valid_percent_encoding(value: str) -> bool:
    index = 0
    while index < len(value):
        if value[index] != "%":
            index += 1
            continue
        if index + 2 >= len(value):
            return False
        chunk = value[index + 1 : index + 3]
        if any(character not in _HEX_DIGITS for character in chunk):
            return False
        index += 3
    return True


def _include_error(
    message: str,
    *,
    code: str,
    source: ConfigSource,
    include_site_path: ConfigPath,
    authored_target: str,
    expected: object | None = None,
    actual: object | None = None,
    details: dict[str, object] | None = None,
) -> ConfigIncludeResolutionError:
    payload = dict(details or {})
    payload["authored_target"] = authored_target
    return ConfigIncludeResolutionError(
        message,
        context=ConfigErrorContext(
            code=code,
            source_kind=source.kind,
            source_order=source.order,
            source_path=str(source.path),
            config_path=format_config_path(include_site_path),
            expected=expected,
            actual=actual,
            details=payload,
        ),
    )
