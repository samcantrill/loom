"""Internal include target resolution helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Never, cast
from urllib.parse import ParseResult, unquote_to_bytes, urlparse

from loom.serialization import PlainData, to_plain_data

from .errors import (
    ConfigErrorContext,
    ConfigIncludeExpansionError,
    ConfigIncludeResolutionError,
    ConfigLoadError,
)
from .load import load_config, load_config_with_source_text
from .provenance import ConfigSource
from .redaction import (
    REDACTION_MARKER,
    contains_secret_like_value,
    is_secret_path,
    redact_secret_like_value,
)
from .source_maps import ConfigPath, build_base_source_map, format_config_path
from .merge import merge_configs

IncludeTargetKind = Literal["bare_name", "explicit_relative", "absolute", "file_uri"]
ConfigSourceKind = Literal["base", "overlay"]

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


CustomizationKind = Literal["add", "override"]


@dataclass(frozen=True, slots=True)
class IncludeLocalCustomization:
    include_site_path: ConfigPath
    sibling_path: ConfigPath
    source_path: str
    source_kind: ConfigSourceKind
    source_order: int
    kind: CustomizationKind
    value: PlainData

    def to_dict(self) -> dict[str, object]:
        final_key = self.sibling_path[-1] if self.sibling_path and isinstance(self.sibling_path[-1], str) else ""
        path_redacted = is_secret_path(self.sibling_path)
        redacted = path_redacted or contains_secret_like_value(final_key, self.value)
        return {
            "include_site_path": _format_path(self.include_site_path),
            "sibling_path": _format_path(self.sibling_path),
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "source_order": self.source_order,
            "kind": self.kind,
            "value": (
                REDACTION_MARKER if path_redacted else redact_secret_like_value(final_key, self.value)
            ),
            "redacted": redacted,
        }


@dataclass(frozen=True, slots=True)
class IncludeSiteRecord:
    include_site_path: ConfigPath
    authored_target: str
    source_path: str
    source_kind: ConfigSourceKind
    source_order: int
    source_include_site_path: ConfigPath
    source_content_digest: str
    source_size_bytes: int
    resolved_path: str
    included_content_digest: str
    included_size_bytes: int
    target_kind: IncludeTargetKind
    explicit_escape: bool
    has_replace_marker: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "include_site_path": _format_path(self.include_site_path),
            "authored_target": self.authored_target,
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "source_order": self.source_order,
            "source_include_site_path": _format_path(self.source_include_site_path),
            "source_content_digest": self.source_content_digest,
            "source_size_bytes": self.source_size_bytes,
            "included_content_digest": self.included_content_digest,
            "included_size_bytes": self.included_size_bytes,
            "resolved_path": self.resolved_path,
            "target_kind": self.target_kind,
            "explicit_escape": self.explicit_escape,
            "has_replace_marker": self.has_replace_marker,
        }


@dataclass(frozen=True, slots=True)
class IncludeRecompositionContext:
    include_site_path: ConfigPath
    source_include_site_path: ConfigPath
    source_path: str
    source_kind: ConfigSourceKind
    source_order: int
    source_content_digest: str
    source_size_bytes: int
    local_customizations: tuple[IncludeLocalCustomization, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "include_site_path": _format_path(self.include_site_path),
            "source_include_site_path": _format_path(self.source_include_site_path),
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "source_order": self.source_order,
            "source_content_digest": self.source_content_digest,
            "source_size_bytes": self.source_size_bytes,
            "local_customizations": [record.to_dict() for record in self.local_customizations],
        }


@dataclass(frozen=True, slots=True)
class IncludeStackFrame:
    include_site_path: ConfigPath
    authored_target: str
    source_path: str
    source_kind: ConfigSourceKind
    source_order: int
    resolved_path: str
    target_kind: IncludeTargetKind
    explicit_escape: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "include_site_path": _format_path(self.include_site_path),
            "authored_target": self.authored_target,
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "source_order": self.source_order,
            "resolved_path": self.resolved_path,
            "target_kind": self.target_kind,
            "explicit_escape": self.explicit_escape,
        }


@dataclass(frozen=True, slots=True)
class ExpandedConfigWithIncludes:
    config: dict[str, PlainData]
    include_sites: tuple[IncludeSiteRecord, ...]
    local_customizations: tuple[IncludeLocalCustomization, ...]
    recomposition_contexts: tuple[IncludeRecompositionContext, ...]


def _format_path(include_path: ConfigPath) -> list[str | int]:
    return [segment for segment in include_path]


def expand_config_includes(
    config: Mapping[str, PlainData],
    source_map: dict[ConfigPath, ConfigSource],
    *,
    path_prefix: ConfigPath = (),
    replacement_sites: Sequence[ConfigPath] = (),
    mapping_sites: Sequence[ConfigPath] = (),
    reject_unconsumed_replace_markers: bool = False,
    raw_source_texts: dict[str, str] | None = None,
) -> ExpandedConfigWithIncludes:
    """Expand file-authored `_include_` directives recursively."""

    include_sites: list[IncludeSiteRecord] = []
    local_customizations: list[IncludeLocalCustomization] = []
    recomposition_contexts: list[IncludeRecompositionContext] = []
    include_stack: list[IncludeStackFrame] = []
    expanded_mapping = _expand_value_with_includes(
        value=cast(dict[str, PlainData], config),
        source_map=source_map,
        path=path_prefix,
        source_lookup_path=(),
        replacement_sites=tuple(replacement_sites),
        mapping_sites=tuple(mapping_sites),
        include_sites=include_sites,
        local_customizations=local_customizations,
        recomposition_contexts=recomposition_contexts,
        include_stack=include_stack,
        reject_unconsumed_replace_markers=reject_unconsumed_replace_markers,
        raw_source_texts=raw_source_texts,
    )

    return ExpandedConfigWithIncludes(
        config=cast(dict[str, PlainData], expanded_mapping),
        include_sites=tuple(include_sites),
        local_customizations=tuple(local_customizations),
        recomposition_contexts=tuple(recomposition_contexts),
    )


def _expand_value_with_includes(
    *,
    value: PlainData,
    source_map: Mapping[ConfigPath, ConfigSource],
    path: ConfigPath,
    source_lookup_path: ConfigPath,
    replacement_sites: tuple[ConfigPath, ...],
    mapping_sites: tuple[ConfigPath, ...],
    raw_source_texts: dict[str, str] | None,
    include_sites: list[IncludeSiteRecord],
    local_customizations: list[IncludeLocalCustomization],
    recomposition_contexts: list[IncludeRecompositionContext],
    include_stack: list[IncludeStackFrame],
    reject_unconsumed_replace_markers: bool,
) -> PlainData:
    if not isinstance(value, Mapping):
        if isinstance(value, list):
            return [
                _expand_value_with_includes(
                    value=child,
                    source_map=source_map,
                    path=path + (index,),
                    source_lookup_path=source_lookup_path + (index,),
                    replacement_sites=replacement_sites,
                    mapping_sites=mapping_sites,
                    raw_source_texts=raw_source_texts,
                    include_sites=include_sites,
                    local_customizations=local_customizations,
                    recomposition_contexts=recomposition_contexts,
                    include_stack=include_stack,
                    reject_unconsumed_replace_markers=reject_unconsumed_replace_markers,
                )
                for index, child in enumerate(value)
            ]

        return value

    mapping = cast(dict[str, PlainData], value)
    expanded_mapping = {}
    if "_include_" in mapping:
        return _expand_including_mapping(
            mapping=mapping,
            source_map=source_map,
            path=path,
            source_lookup_path=source_lookup_path,
            replacement_sites=replacement_sites,
            mapping_sites=mapping_sites,
            raw_source_texts=raw_source_texts,
            include_sites=include_sites,
            local_customizations=local_customizations,
            recomposition_contexts=recomposition_contexts,
            include_stack=include_stack,
            reject_unconsumed_replace_markers=reject_unconsumed_replace_markers,
        )

    if reject_unconsumed_replace_markers and "_replace_" in mapping:
        replace_marker_path = path + ("_replace_",)
        source_replace_marker_path = source_lookup_path + ("_replace_",)
        replace_source = _lookup_include_source(
            source_map,
            source_replace_marker_path,
            expect_path=source_replace_marker_path,
            path_kind="replace_marker",
        )
        _raise_unconsumed_included_replace_marker_error(
            source=replace_source,
            replace_marker_path=replace_marker_path,
            source_replace_marker_path=source_replace_marker_path,
            actual=mapping.get("_replace_"),
        )

    for key, child in mapping.items():
        expanded_mapping[key] = _expand_value_with_includes(
            value=cast(PlainData, child),
            source_map=source_map,
            path=path + (key,),
            source_lookup_path=source_lookup_path + (key,),
            replacement_sites=replacement_sites,
            mapping_sites=mapping_sites,
            include_sites=include_sites,
            raw_source_texts=raw_source_texts,
            local_customizations=local_customizations,
            recomposition_contexts=recomposition_contexts,
            include_stack=include_stack,
            reject_unconsumed_replace_markers=reject_unconsumed_replace_markers,
        )
    return expanded_mapping


def _expand_including_mapping(
    *,
    mapping: dict[str, PlainData],
    source_map: Mapping[ConfigPath, ConfigSource],
    path: ConfigPath,
    source_lookup_path: ConfigPath,
    replacement_sites: tuple[ConfigPath, ...],
    mapping_sites: tuple[ConfigPath, ...],
    raw_source_texts: dict[str, str] | None,
    include_sites: list[IncludeSiteRecord],
    local_customizations: list[IncludeLocalCustomization],
    recomposition_contexts: list[IncludeRecompositionContext],
    include_stack: list[IncludeStackFrame],
    reject_unconsumed_replace_markers: bool,
) -> dict[str, PlainData]:
    include_site_path = path + ("_include_",)
    source_include_site_path = source_lookup_path + ("_include_",)
    include_source = _lookup_include_source(source_map, source_include_site_path)
    authored_target = mapping.get("_include_")
    if not isinstance(authored_target, str):
        raise _include_expansion_error(
            "Include target must be a string.",
            code="invalid_include_value",
            source=include_source,
            include_site_path=include_site_path,
            authored_target=_display_value(authored_target),
            details={
                "reason": "include_value_not_string",
                "include_site_path": _format_path(include_site_path),
            },
        )

    try:
        resolution = resolve_include_target(
            authored_target,
            source=include_source,
            include_site_path=source_include_site_path,
        )
    except ConfigIncludeResolutionError as exc:
        raise _augment_include_error_with_stack(exc, include_stack=include_stack) from exc

    _validate_include_cycle(
        resolution=resolution,
        include_site_path=include_site_path,
        include_source=include_source,
        include_stack=include_stack,
    )

    include_frame = IncludeStackFrame(
        include_site_path=include_site_path,
        authored_target=authored_target,
        source_path=resolution.source_path,
        source_kind=include_source.kind,
        source_order=include_source.order,
        resolved_path=str(resolution.resolved_path),
        target_kind=resolution.target_kind,
        explicit_escape=resolution.explicit_escape,
    )
    include_stack.append(include_frame)
    try:
        container_path = path
        container_source = source_map.get(container_path)
        if container_source is not None:
            if (
                container_path in mapping_sites
                and container_path not in replacement_sites
                and container_source.order <= include_source.order
            ):
                raise _include_expansion_error(
                    "Include replacement over existing mapping requires same-site _replace_: true.",
                    code="missing_required_replace_for_include",
                    source=include_source,
                    include_site_path=include_site_path,
                    authored_target=authored_target,
                    details={
                        "reason": "include_over_existing_mapping",
                        "include_site_path": _format_path(include_site_path),
                        "container_path": _format_path(container_path),
                        "resolved_path": str(resolution.resolved_path),
                        "container_source_order": container_source.order,
                        "include_source_order": include_source.order,
                    },
                )

        try:
            if raw_source_texts is None:
                included_config, included_source = load_config(
                    resolution.resolved_path,
                    kind="overlay",
                    order=0,
                )
            else:
                included_config, included_source, source_text = load_config_with_source_text(
                    resolution.resolved_path,
                    kind="overlay",
                    order=0,
                )
                raw_source_texts[included_source.path] = source_text
        except ConfigLoadError as exc:
            if exc.context is None or exc.context.code != "non_mapping_root":
                raise
            raise _include_expansion_error(
                "Included root must be a mapping.",
                code="included_root_not_mapping",
                source=include_source,
                include_site_path=include_site_path,
                authored_target=authored_target,
                expected=exc.context.expected,
                actual=exc.context.actual,
                details={
                    "reason": "included_root_not_mapping",
                    "include_site_path": _format_path(include_site_path),
                    "resolved_path": str(resolution.resolved_path),
                    "included_source_path": exc.context.source_path,
                },
            ) from exc
        included_source_map = build_base_source_map(included_config, included_source)
        include_sites.append(
            IncludeSiteRecord(
                include_site_path=include_site_path,
                authored_target=authored_target,
                source_path=resolution.source_path,
                source_kind=include_source.kind,
                source_order=include_source.order,
                source_include_site_path=source_include_site_path,
                source_content_digest=include_source.content_digest,
                source_size_bytes=include_source.size_bytes,
                resolved_path=str(resolution.resolved_path),
                included_content_digest=included_source.content_digest,
                included_size_bytes=included_source.size_bytes,
                has_replace_marker=("_replace_" in mapping),
                target_kind=resolution.target_kind,
                explicit_escape=resolution.explicit_escape,
            ),
        )
        shifted_included_map = _expand_value_with_includes(
            value=included_config,
            source_map=included_source_map,
            path=container_path,
            source_lookup_path=(),
            replacement_sites=(),
            mapping_sites=(),
            include_sites=include_sites,
            raw_source_texts=raw_source_texts,
            local_customizations=local_customizations,
            recomposition_contexts=recomposition_contexts,
            include_stack=include_stack,
            reject_unconsumed_replace_markers=True,
        )

        if not isinstance(shifted_included_map, Mapping):
            raise _include_expansion_error(
                "Included root must be a mapping.",
                code="included_root_not_mapping",
                source=include_source,
                include_site_path=include_site_path,
                authored_target=authored_target,
                details={
                    "reason": "included_root_not_mapping",
                    "include_site_path": _format_path(include_site_path),
                    "resolved_path": str(resolution.resolved_path),
                    "resolved_kind": str(type(shifted_included_map)),
                },
            )
    except (ConfigIncludeExpansionError, ConfigIncludeResolutionError) as exc:
        raise _augment_include_error_with_stack(exc, include_stack=include_stack) from exc
    finally:
        include_stack.pop()

    included_mapping = cast(dict[str, PlainData], shifted_included_map)

    _validate_local_replace_marker(
        mapping=mapping,
        include_source=include_source,
        include_site_path=include_site_path,
        authored_target=authored_target,
        replacement_sites=replacement_sites,
        path=container_path,
        resolved_path=resolution.resolved_path,
    )
    local_mapping = {key: value for key, value in mapping.items() if key not in {"_include_", "_replace_"}}
    local_expanded = {}
    local_customizations_for_site: list[IncludeLocalCustomization] = []
    for key, child in local_mapping.items():
        sibling_path = include_site_path[:-1] + (key,)
        source_sibling_path = source_lookup_path + (key,)
        sibling_source = _lookup_include_source(
            source_map,
            source_sibling_path,
            expect_path=source_sibling_path,
            path_kind="sibling",
        )
        local_expanded_value = _expand_value_with_includes(
            value=child,
            source_map=source_map,
            path=sibling_path,
            source_lookup_path=source_sibling_path,
            replacement_sites=(),
            mapping_sites=(),
            include_sites=include_sites,
            raw_source_texts=raw_source_texts,
            local_customizations=local_customizations,
            recomposition_contexts=recomposition_contexts,
            include_stack=include_stack,
            reject_unconsumed_replace_markers=reject_unconsumed_replace_markers,
        )
        custom_kind: CustomizationKind = "override" if key in included_mapping else "add"
        customization_record = IncludeLocalCustomization(
            include_site_path=include_site_path,
            sibling_path=sibling_path,
            source_path=sibling_source.path,
            source_kind=sibling_source.kind,
            source_order=sibling_source.order,
            kind=custom_kind,
            value=local_expanded_value,
        )
        local_customizations.append(customization_record)
        local_customizations_for_site.append(customization_record)
        local_expanded[key] = local_expanded_value

    recomposition_contexts.append(
        IncludeRecompositionContext(
            include_site_path=include_site_path,
            source_include_site_path=source_include_site_path,
            source_path=include_source.path,
            source_kind=include_source.kind,
            source_order=include_source.order,
            source_content_digest=include_source.content_digest,
            source_size_bytes=include_source.size_bytes,
            local_customizations=tuple(local_customizations_for_site),
        )
    )

    merged = merge_configs(
        included_mapping,
        local_expanded,
        path=format_config_path(container_path),
    )

    return merged


def _raise_unconsumed_included_replace_marker_error(
    *,
    source: ConfigSource,
    replace_marker_path: ConfigPath,
    source_replace_marker_path: ConfigPath,
    actual: object,
) -> Never:
    raise _include_expansion_error(
        "Unexpected _replace_ marker in included content.",
        code="invalid_included_replace_marker",
        source=source,
        include_site_path=replace_marker_path,
        authored_target="",
        actual=actual,
        directive="_replace_",
        details={
            "reason": "unconsumed_included_replace_marker",
            "replace_marker_path": _format_path(replace_marker_path),
            "source_replace_marker_path": _format_path(source_replace_marker_path),
            "container_path": _format_path(replace_marker_path[:-1]),
        },
    )


def _validate_local_replace_marker(
    *,
    mapping: Mapping[str, PlainData],
    include_source: ConfigSource,
    include_site_path: ConfigPath,
    authored_target: str,
    replacement_sites: tuple[ConfigPath, ...],
    path: ConfigPath,
    resolved_path: Path,
) -> None:
    if "_replace_" not in mapping or path in replacement_sites:
        return

    raise _include_expansion_error(
        "Unexpected _replace_ marker beside _include_.",
        code="invalid_include_replace_marker",
        source=include_source,
        include_site_path=include_site_path,
        authored_target=authored_target,
        details={
            "reason": "unexpected_replace_marker",
            "include_site_path": _format_path(include_site_path),
            "container_path": _format_path(path),
            "resolved_path": str(resolved_path),
        },
    )


def _validate_include_cycle(
    *,
    resolution: IncludeResolutionResult,
    include_site_path: ConfigPath,
    include_source: ConfigSource,
    include_stack: list[IncludeStackFrame],
) -> None:
    for frame in include_stack:
        if frame.resolved_path == str(resolution.resolved_path):
            raise _include_expansion_error(
                "Include cycle detected.",
                code="include_cycle",
                source=include_source,
                include_site_path=include_site_path,
                authored_target=resolution.authored_target,
                details={
                    "reason": "include_cycle",
                    "attempted_target": str(resolution.resolved_path),
                    "attempted_include_site_path": _format_path(include_site_path),
                    "include_stack": [_format_stack_frame(frame) for frame in include_stack],
                },
            )


def _format_stack_frame(frame: IncludeStackFrame) -> dict[str, object]:
    return frame.to_dict()


def _lookup_include_source(
    source_map: Mapping[ConfigPath, ConfigSource],
    include_site_path: ConfigPath,
    *,
    expect_path: ConfigPath | None = None,
    path_kind: Literal["include", "sibling", "replace_marker"] = "include",
) -> ConfigSource:
    include_source = source_map.get(include_site_path)
    if include_source is not None:
        return include_source

    details = {
        "reason": f"missing_{path_kind}_source_map_entry",
        "include_site_path": _format_path(include_site_path),
    }
    if expect_path is not None:
        details["expected_path"] = _format_path(expect_path)
    return _raise_include_source_error(include_site_path=include_site_path, details=details)


def _display_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return f"<{type(value).__name__}>"


def _raise_include_source_error(
    *,
    include_site_path: ConfigPath,
    details: dict[str, object],
) -> Never:
    raise _include_expansion_error(
        "Could not locate include-site source metadata for include expansion.",
        code="missing_include_source_map_entry",
        source=ConfigSource(
            kind="overlay",
            path="<missing>",
            order=-1,
            content_digest="sha256:missing",
            size_bytes=0,
        ),
        include_site_path=include_site_path,
        authored_target="",
        details=details,
    )


def _include_expansion_error(
    message: str,
    *,
    code: str,
    source: ConfigSource,
    include_site_path: ConfigPath,
    authored_target: str,
    directive: str = "_include_",
    expected: object | None = None,
    actual: object | None = None,
    details: dict[str, object] | None = None,
) -> ConfigIncludeExpansionError:
    payload = dict(details or {})
    payload["authored_target"] = authored_target
    plain_details = to_plain_data(payload)
    if not isinstance(plain_details, dict):
        raise TypeError("Config include expansion error details must be a mapping")

    return ConfigIncludeExpansionError(
        message,
        context=ConfigErrorContext(
            code=code,
            source_kind=source.kind,
            source_order=source.order,
            source_path=str(source.path),
            config_path=format_config_path(include_site_path),
            expected=_optional_plain_data(expected),
            actual=_optional_plain_data(actual),
            directive=directive,
            remediation=_include_remediation(code),
            details=cast(dict[str, PlainData], plain_details),
        ),
    )


def _augment_include_error_with_stack(
    error: ConfigIncludeExpansionError | ConfigIncludeResolutionError,
    *,
    include_stack: Sequence[IncludeStackFrame],
) -> ConfigIncludeExpansionError | ConfigIncludeResolutionError:
    if error.context is None:
        return error
    details = dict(error.context.details or {})
    details.setdefault(
        "active_include_stack",
        cast(PlainData, [_format_stack_frame(frame) for frame in include_stack]),
    )
    augmented_context = ConfigErrorContext(
        code=error.context.code,
        source_kind=error.context.source_kind,
        source_order=error.context.source_order,
        source_path=error.context.source_path,
        config_path=error.context.config_path,
        expected=error.context.expected,
        actual=error.context.actual,
        directive=error.context.directive,
        remediation=error.context.remediation or _include_remediation(error.context.code),
        details=cast(dict[str, PlainData], to_plain_data(details)),
    )
    return type(error)(str(error), context=augmented_context)


def _include_remediation(code: str) -> str | None:
    return {
        "target_not_found": "Check the include target path relative to the authoring file, or use an explicit relative target.",
        "target_not_file": "Point the include target at a regular YAML file.",
        "unsupported_target_form": "Use a bare-name token or an explicit relative, absolute, or file:// include target.",
        "resolver_dependent": "Use oc.env in ordinary values, not in include targets.",
        "missing_required_replace_for_include": "Add _replace_: true beside _include_ when replacing an existing mapping.",
        "invalid_include_value": "Set _include_ to a string target.",
        "included_root_not_mapping": "Change the included file so its root is a mapping.",
        "invalid_include_replace_marker": "Remove the local _replace_ marker or place it at the same include replacement site.",
        "invalid_included_replace_marker": "Remove _replace_ from the included file root or consume it at an authored replacement site.",
        "include_cycle": "Break the include cycle by removing one include edge or changing the target.",
    }.get(code)


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

    target_path = Path(target)
    if target_path.is_absolute():
        return _validate_candidate(
            target=target,
            candidate=target_path,
            source=source,
            include_site_path=include_site_path,
            kind="absolute",
            explicit_escape=True,
        )

    if _is_explicit_relative_target(target):
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
    parsed: ParseResult,
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

    if not target.lower().startswith("file://"):
        raise _include_error(
            "file URI targets must use file:// form.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            details={
                "scheme": scheme,
                "reason": "ambiguous_file_uri_form",
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
    decoded_path = _decode_file_uri_path(
        raw_path=raw_path,
        source=source,
        include_site_path=include_site_path,
        authored_target=target,
    )
    _validate_decoded_file_uri_path(
        decoded_path=decoded_path,
        raw_path=raw_path,
        source=source,
        include_site_path=include_site_path,
        authored_target=target,
    )
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
                details={
                    "reason": "include_site_segment_type",
                    "segment": repr(segment),
                },
            )
        _validate_bare_parent_segment(
            segment=segment,
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
        )
        derived_dir = derived_dir / segment

    candidate = derived_dir / f"{target}.yaml"
    normalized_candidate = candidate.resolve(strict=False)
    _validate_bare_candidate_contained(
        target=target,
        derived_dir=derived_dir,
        candidate=normalized_candidate,
        source=source,
        include_site_path=include_site_path,
    )
    return _validate_candidate(
        target=target,
        candidate=normalized_candidate,
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
    normalized_candidate = candidate.resolve(strict=False)

    if not normalized_candidate.exists():
        raise _include_error(
            f"Include target does not resolve to an existing file: {normalized_candidate}",
            code="target_not_found",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            expected="existing regular file",
            actual="missing target",
            details={
                "candidate_path": str(normalized_candidate),
                "target_kind": kind,
                "explicit_escape": explicit_escape,
                **(details or {}),
            },
        )

    if not normalized_candidate.is_file():
        raise _include_error(
            f"Include target must resolve to a regular file: {normalized_candidate}",
            code="target_not_file",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            expected="regular file",
            actual="directory",
            details={
                "candidate_path": str(normalized_candidate),
                "target_kind": kind,
                "explicit_escape": explicit_escape,
                **(details or {}),
            },
        )

    return IncludeResolutionResult(
        authored_target=target,
        include_site_path=include_site_path,
        source_path=str(source.path),
        resolved_path=normalized_candidate,
        target_kind=kind,
        explicit_escape=explicit_escape,
    )


def _validate_include_site_path(
    source: ConfigSource, include_site_path: ConfigPath
) -> None:
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
                details={
                    "reason": "include_site_segment_type",
                    "segment": repr(segment),
                },
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


def _validate_bare_candidate_contained(
    *,
    target: str,
    derived_dir: Path,
    candidate: Path,
    source: ConfigSource,
    include_site_path: ConfigPath,
) -> None:
    derived_root = derived_dir.absolute()
    try:
        candidate.relative_to(derived_root)
    except ValueError as exc:
        raise _include_error(
            "Bare-name include target resolved outside its derived config directory.",
            code="unsafe_include_target",
            source=source,
            include_site_path=include_site_path,
            authored_target=target,
            expected="normalized bare-name target under derived config directory",
            actual=str(candidate),
            details={
                "candidate_path": str(candidate),
                "resolved_path": str(candidate),
                "derived_dir": str(derived_dir),
                "target_kind": "bare_name",
                "explicit_escape": False,
                "reason": "bare_name_symlink_escape",
            },
        ) from exc


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
            details={
                "scheme": "file",
                "path": raw_path,
                "reason": "empty_file_uri_path",
            },
        )

    if "%" in raw_path and not _is_valid_percent_encoding(raw_path):
        raise _include_error(
            "Malformed percent escape in file URI path.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={
                "scheme": "file",
                "path": raw_path,
                "reason": "malformed_percent_escape",
            },
        )

    lowered = raw_path.lower()
    if "%2f" in lowered:
        raise _include_error(
            "Escaped path separators are not supported in file URI targets.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={
                "scheme": "file",
                "path": raw_path,
                "reason": "escaped_path_separator",
            },
        )

    if "%5c" in lowered:
        raise _include_error(
            "Escaped path separators are not supported in file URI targets.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={
                "scheme": "file",
                "path": raw_path,
                "reason": "escaped_path_separator",
            },
        )

    if "%2e" in lowered:
        raise _include_error(
            "Encoded dot segments are not supported in file URI targets.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={
                "scheme": "file",
                "path": raw_path,
                "reason": "encoded_dot_segment",
            },
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


def _decode_file_uri_path(
    *,
    raw_path: str,
    source: ConfigSource,
    include_site_path: ConfigPath,
    authored_target: str,
) -> str:
    try:
        return unquote_to_bytes(raw_path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _include_error(
            "file URI percent escapes must decode as valid UTF-8.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={
                "scheme": "file",
                "path": raw_path,
                "reason": "invalid_utf8_percent_escape",
            },
        ) from exc


def _validate_decoded_file_uri_path(
    *,
    decoded_path: str,
    raw_path: str,
    source: ConfigSource,
    include_site_path: ConfigPath,
    authored_target: str,
) -> None:
    if "\x00" in decoded_path:
        raise _include_error(
            "file URI paths may not contain embedded NUL bytes.",
            code="invalid_file_uri",
            source=source,
            include_site_path=include_site_path,
            authored_target=authored_target,
            details={
                "scheme": "file",
                "path": raw_path,
                "reason": "embedded_nul_byte",
            },
        )


def _is_explicit_relative_target(target: str) -> bool:
    if target.startswith(("./", "../")):
        return True
    if "/" in target:
        return True
    if target.startswith("."):
        return False
    return bool(Path(target).suffix)


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
    plain_details = to_plain_data(payload)
    if not isinstance(plain_details, dict):
        raise TypeError("Config include resolution error details must be a mapping")

    return ConfigIncludeResolutionError(
        message,
        context=ConfigErrorContext(
            code=code,
            source_kind=source.kind,
            source_order=source.order,
            source_path=str(source.path),
            config_path=format_config_path(include_site_path),
            expected=_optional_plain_data(expected),
            actual=_optional_plain_data(actual),
            remediation=_include_remediation(code),
            details=cast(dict[str, PlainData], plain_details),
        ),
    )


def _optional_plain_data(value: object | None) -> PlainData | None:
    if value is None:
        return None
    return to_plain_data(value)
