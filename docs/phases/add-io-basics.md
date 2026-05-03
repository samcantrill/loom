# Phase 3 Expanded Plan: I/O Basics

## Metadata

- Status: final expanded plan.
- Branch: `codex/add-io-basics`.
- Worktree: `/home/samcantrill/work/loom-worktrees/add-io-basics`.
- Expanded plan path: `docs/phases/add-io-basics.md`.
- Full plan: `docs/implementation-plans/implementation-plan-v0.md`.
- Source phase: `Phase 3 - I/O Basics`.
- Base branch: local `develop` at `3a3eb4f253617d13f0d74ddfd51742574e785db6` (`docs: mark phase 2 merged`).
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no remaining blockers are recorded in the canonical v0 plan.
- Plan quality gate loop budget: initial plan review used, automated plan refinement pass used, confirmation review used. Do not start another plan-quality review loop for this phase unless the manager explicitly instructs it.
- Setup limitation: manager preflight recorded that `git fetch origin develop` and `git push origin develop` are unavailable in this environment because SSH public-key authentication and `ssh_askpass` are not configured. This branch and worktree were created from local `develop`.
- Worktree creation note: the first sandboxed `git worktree add` attempt could not write repository refs because `.git/refs` was read-only in the sandbox; the approved rerun created the branch and worktree. This is an environment limitation, not a product blocker.
- Prior phase state: Phase 1 and Phase 2 are recorded as merged locally in the canonical plan. Phase 3 remains pending in the canonical plan at final-plan time.
- Blockers: none.

## Objective

Implement the first concrete `loom.io` layer: local URI helpers, local filesystem access, generic JSON/text/bytes codecs, codec-specific errors, and an explicit instance-based codec registry.

This phase makes I/O the bridge between stored bytes and already-serialized plain data. Serialization owns Python-object to plain-structured-data conversion. Stores own artifact path allocation, atomic writes, checksums, run layout, indexes, and managed artifact save/load policy.

## Full-Plan Context

The v0 plan builds `loom` as a typed, domain-neutral runtime in small phases. Phase 1 created import-safe package skeletons, broad error roots, timestamp/id helpers, and import-boundary tests. Phase 2 implemented primitives, provenance, fingerprints, and serialization helpers, including `ResourceRef`, `ArtifactRef`, `CodecKey`, `PlainData`, `ensure_plain_data`, `json_loads`, and deterministic JSON helpers.

Phase 3 is the first behavior-bearing I/O phase. Later phases depend on it as follows:

- Phase 4 config composition must remain independent from I/O and must not gain filesystem persistence behavior.
- Phase 5 recipes and instantiation may create or pass codec registry instances, but recipe catalogs, target imports, and config-driven codec construction are out of this phase.
- Phase 7 local stores will use codecs and local filesystem access for managed artifact save/load, checksum calculation, manual registration, and run layout persistence.
- Phase 8 planning/resume will rely on stores for checksum validation and must not compute resume policy in the I/O layer.
- Phase 9 local execution will receive store-backed artifact helpers. Passive `ResourceRef` and `ArtifactRef` values must not load themselves.

Controlling constraints:

- Keep `loom` domain-neutral. Do not add dataset, model, array, image, video, report, checkpoint, table, compressed-format, pickle, YAML, or project-specific codecs.
- Keep runtime dependencies empty and standard-library only.
- Preserve import direction from `docs/structure.md`: primitives and serialization do not import I/O; I/O does not import config composition, pipeline runners, stores, CLI, plugins, optional remote backends, or downstream project packages.
- Keep `loom.__init__` cheap and unchanged in this phase.
- Use structural protocols and explicit instance registries, not inheritance-heavy frameworks or mutable global registries.
- Treat feature documents as detailed guidance only where they do not widen the approved Phase 3 scope.

## Source Phase Summary

From `docs/implementation-plans/implementation-plan-v0.md`, Phase 3 is `Status: pending` with branch `codex/add-io-basics` and PR `pending`.

Goal:

- Implement local filesystem access, URI helpers, generic codecs, and codec registration.

Required scope:

- Add URI parsing and normalization helpers.
- Add `DataSource` protocol and `LocalFileSystemSource`.
- Add `Codec` protocol, JSON/text/bytes codecs, codec-specific errors, and an explicit instance-based `CodecRegistry`.
- Keep this layer as the bridge between plain serialized data and stored bytes.

Required checkpoints:

- URI helpers include `parse_uri`, `is_file_uri`, `uri_to_path`, `path_to_file_uri`, `normalize_uri`, and `get_uri_scheme`.
- `LocalFileSystemSource` supports local paths and `file://` URIs with `open`, `exists`, `stat`, `glob`, and `resolve`.
- `JSONCodec` accepts only plain-data-compatible values; `TextCodec` is UTF-8 by default; `BytesCodec` handles raw bytes only.
- `CodecRegistry` is instance-based and rejects duplicate registrations and unknown codec keys.

Acceptance criteria:

- Local paths and `file://` URIs round-trip correctly.
- Local source supports `open`, `exists`, `stat`, `glob`, and path resolution.
- JSON/text/bytes codecs round-trip supported values.
- JSON codec rejects non-plain unsupported objects.
- Codec registry rejects duplicate keys and unknown codec lookups.

## Current Source And Harness Findings

- `src/loom/io/__init__.py` is still the Phase 1 skeleton with empty `__all__`.
- `src/loom/errors.py` already defines `IOErrorBase`; Phase 3 I/O errors must inherit from it through a concrete `LoomIOError`.
- `src/loom/ids.py` already defines `CodecKey = str`; do not add key wrapper classes.
- `src/loom/serialization/plain.py` already provides `PlainData`, `ensure_plain_data`, and `to_plain_data`. `JSONCodec.encode` must call `ensure_plain_data`, not `to_plain_data`, so arbitrary dataclasses or objects with `to_dict()` are rejected by I/O.
- `src/loom/serialization/json.py` currently has `json_dumps_pretty`, `stable_json_bytes`, and `json_loads`. `json_dumps_pretty` internally calls `to_plain_data`, so `JSONCodec` must validate with `ensure_plain_data` before calling it.
- `src/loom/timestamps.py` provides UTC timestamp formatting. `LocalFileSystemSource.stat` should use it for `mtime`.
- The Make harness has concrete targets for package, unit, contract, integration, e2e, all, summary, and PR validation. `tests/contracts`, `tests/integration`, and `tests/e2e` directories are currently absent, but the harness reports missing suite directories as `not present`.
- Existing package import-boundary tests prove serialization does not import I/O and top-level `import loom` does not import config, pipeline, or CLI. Phase 3 must extend these tests to include I/O boundaries without changing top-level exports.

## In-Scope Work

- Replace the empty `src/loom/io/__init__.py` skeleton with stable Phase 3 exports for URI helpers, source/codec protocols, the local source, generic codecs, the codec registry, and I/O errors.
- Add `src/loom/io/errors.py` with `LoomIOError(IOErrorBase)` and `UnsupportedURIError`.
- Add `src/loom/io/uris.py` with `ParsedURI`, `parse_uri`, `get_uri_scheme`, `is_file_uri`, `uri_to_path`, `path_to_file_uri`, and `normalize_uri`.
- Add `src/loom/io/sources/` with `base.py`, `local.py`, `errors.py`, and `__init__.py`.
- Add `src/loom/io/codecs/` with `base.py`, `json_codec.py`, `text_codec.py`, `bytes_codec.py`, `registry.py`, `errors.py`, and `__init__.py`.
- Add package, unit, contract, and integration tests for the implemented Phase 3 behavior.

## Out-of-Scope Work

- No `SourceRegistry`, default source registry, source plugin discovery, source replacement policy, or automatic source lookup by URI scheme.
- No `load_resource`, `load_artifact`, `read_uri_bytes`, `write_uri_bytes`, registry-level source load/save helpers, or reference-based loading helpers.
- No artifact-store layout, local artifact store, run store, atomic write helpers, artifact path allocation, run status files, artifact indexes, checksum validation policy, or store-managed save/load behavior.
- No file checksum, stream checksum, URI checksum, or checksum verification helpers in I/O. Phase 7 owns stored-byte checksums for local stores.
- No remote sources, HTTP/S3/GCS/Azure support, fsspec dependency, network access, package-resource source, database-backed resources, or optional backend extras.
- No domain codecs, unsafe codecs, compression codecs, extension-to-codec inference, or codec selection from URI suffixes, resource types, or artifact types.
- No config composition, recipe expansion, target instantiation, config-driven codec construction, pipeline specs, stage contexts, runner behavior, selectors, resume, stores, or CLI behavior.
- No top-level `loom.__init__` I/O re-exports.
- No canonical implementation-plan phase status update, PR body creation, broad validation run, PR opening, remote push, or product-code implementation during this planning pass.

## Assumptions

- Local `develop` at `3a3eb4f253617d13f0d74ddfd51742574e785db6` is the manager-approved Phase 3 base because remote synchronization is unavailable in this environment.
- POSIX local filesystem behavior is the primary v0 target. Windows drive-letter and UNC path behavior are deferred unless a current test unexpectedly requires them.
- URI helper inputs may accept `str | Path` where that is natural for local paths, but persisted references remain URI strings.
- Empty strings and strings with surrounding whitespace are invalid URI/path inputs. Helpers must reject them rather than stripping silently.
- Relative path base resolution is caller-owned. URI parsing must not turn relative paths into absolute paths.
- `path_to_file_uri` requires an absolute local path and does not require the path to exist.
- `uri_to_path` accepts local `file://` URIs, absolute local paths, and relative local paths. It rejects remote schemes and non-local file authorities.
- `normalize_uri` returns a `file://` URI for local file URIs and absolute local paths. For relative local paths, it returns a normalized relative path unless `base_dir` is supplied, in which case it returns a `file://` URI for the resolved path under `base_dir`.
- `LocalFileSystemSource.resolve` returns an absolute `Path`. With `root=None`, resolving a relative path may depend on the process current working directory; this is accepted Phase 3 debt and is documented below.
- `LocalFileSystemSource.glob` returns sorted normalized `file://` URI strings, not `Path` objects.
- `LocalFileSystemSource.open` provides simple file access only. It may create or truncate the target file in write modes, but it does not create parent directories and does not write atomically.
- `stat` metadata must be plain-data-compatible; no raw `os.stat_result`, `Path`, or `datetime` values should escape.
- Built-in codecs operate on in-memory bytes. Streaming codec protocols are deferred.
- `JSONCodec` accepts already-plain data only. It must reject dataclasses, `Path`, `datetime`, bytes, sets, callables, and arbitrary objects instead of converting them through serialization hooks.
- `TextCodec` encodes only `str` and decodes bytes as UTF-8 by default. It must not silently call `str()`.
- `BytesCodec` handles raw bytes-like inputs only and decodes to `bytes`.
- The codec registry owns registration and dispatch only. It does not select sources, construct refs, compute checksums, update indexes, infer codecs, or manage default global state.
- `create_default_codec_registry()` is in scope because it returns a fresh explicit registry instance every call and does not introduce mutable global state.

## Decision-Complete Public Contract

The executor must treat this section as the implementation contract. If a required public shape conflicts with this section, stop and report the blocker instead of widening the phase.

### Module Layout And Exports

- `src/loom/io/__init__.py`
  - Public `__all__`:
    `["ParsedURI", "parse_uri", "get_uri_scheme", "is_file_uri", "uri_to_path", "path_to_file_uri", "normalize_uri", "LoomIOError", "UnsupportedURIError", "DataSource", "LocalFileSystemSource", "DataSourceError", "SourceNotFoundError", "SourcePermissionError", "UnsupportedSourceOperationError", "Codec", "JSONCodec", "TextCodec", "BytesCodec", "CodecRegistry", "create_default_codec_registry", "CodecError", "CodecRegistrationError", "UnknownCodecError", "CodecEncodeError", "CodecDecodeError"]`.
- `src/loom/io/errors.py`
  - Public `__all__`: `["LoomIOError", "UnsupportedURIError"]`.
- `src/loom/io/uris.py`
  - Public `__all__`: `["ParsedURI", "parse_uri", "get_uri_scheme", "is_file_uri", "uri_to_path", "path_to_file_uri", "normalize_uri"]`.
- `src/loom/io/sources/__init__.py`
  - Public `__all__`: `["DataSource", "LocalFileSystemSource", "DataSourceError", "SourceNotFoundError", "SourcePermissionError", "UnsupportedSourceOperationError"]`.
- `src/loom/io/sources/base.py`
  - Public `__all__`: `["DataSource"]`.
- `src/loom/io/sources/local.py`
  - Public `__all__`: `["LocalFileSystemSource"]`.
- `src/loom/io/sources/errors.py`
  - Public `__all__`: `["DataSourceError", "SourceNotFoundError", "SourcePermissionError", "UnsupportedSourceOperationError"]`.
- `src/loom/io/codecs/__init__.py`
  - Public `__all__`: `["Codec", "JSONCodec", "TextCodec", "BytesCodec", "CodecRegistry", "create_default_codec_registry", "CodecError", "CodecRegistrationError", "UnknownCodecError", "CodecEncodeError", "CodecDecodeError"]`.
- `src/loom/io/codecs/base.py`
  - Public `__all__`: `["Codec"]`.
- `src/loom/io/codecs/json_codec.py`
  - Public `__all__`: `["JSONCodec"]`.
- `src/loom/io/codecs/text_codec.py`
  - Public `__all__`: `["TextCodec"]`.
- `src/loom/io/codecs/bytes_codec.py`
  - Public `__all__`: `["BytesCodec"]`.
- `src/loom/io/codecs/registry.py`
  - Public `__all__`: `["CodecRegistry", "create_default_codec_registry"]`.
- `src/loom/io/codecs/errors.py`
  - Public `__all__`: `["CodecError", "CodecRegistrationError", "UnknownCodecError", "CodecEncodeError", "CodecDecodeError"]`.
- Do not modify `src/loom/__init__.py` in this phase unless a package test exposes a direct blocker. Expected top-level `loom.__all__` remains the Phase 2 list:
  `["__version__", "ResourceRef", "InMemoryManifest", "ManifestView", "Record", "ArtifactRef", "Fingerprint", "hash_mapping"]`.

### Error Hierarchy

- `LoomIOError(IOErrorBase)` is the concrete Phase 3 I/O root.
- `UnsupportedURIError(LoomIOError)` is raised by URI helpers when a URI/path cannot be interpreted as a supported local URI/path.
- Source errors inherit from `DataSourceError(LoomIOError)`:
  - `SourceNotFoundError(DataSourceError)` for missing local resources when absence is exceptional.
  - `SourcePermissionError(DataSourceError)` for permission failures.
  - `UnsupportedSourceOperationError(DataSourceError)` for unsupported modes, unsupported URI schemes in source operations, non-local file authorities, or unsupported source operations.
- Codec errors inherit from `CodecError(LoomIOError)`:
  - `CodecRegistrationError(CodecError)` for invalid codec objects, invalid keys at registration time, and duplicate registrations.
  - `UnknownCodecError(CodecError)` for lookups, encode dispatch, or decode dispatch using an unregistered key.
  - `CodecEncodeError(CodecError)` for encode failures.
  - `CodecDecodeError(CodecError)` for decode failures.
- Concrete error messages must include useful context: URI or path for URI/source errors; source name and operation for source errors; codec key and operation for codec errors; registered keys for unknown codec errors.
- Use exception chaining when wrapping `OSError`, `UnicodeError`, serialization errors, or JSON parse errors.
- Do not add structured error context objects, error codes, diagnostics objects, or new broad roots in Phase 3.

### URI Helpers

- `ParsedURI` is a frozen slots dataclass with fields:
  - `raw: str`
  - `scheme: str | None`
  - `path: str`
  - `authority: str | None = None`
  - `query: str | None = None`
  - `fragment: str | None = None`
- `parse_uri(uri: str | Path) -> ParsedURI`
  - Rejects empty input and string inputs with surrounding whitespace.
  - Treats no-scheme absolute and relative paths as local paths with `scheme=None`.
  - Lowercases explicit schemes for comparison.
  - For `file://` URIs, stores the decoded local path in `path`, stores empty or `localhost` authority as local, and preserves query/fragment fields if present.
  - For non-file remote URIs, preserves parsed authority, path, query, and fragment without converting them to paths.
  - Does not open files, require existence, expand `~`, resolve symlinks, or apply a base directory.
- `get_uri_scheme(uri: str | Path) -> str | None`
  - Returns the lowercased explicit scheme or `None` for local paths.
  - Uses the same invalid-input policy as `parse_uri`.
- `is_file_uri(uri: str | Path) -> bool`
  - Returns `True` only when the explicit scheme is `file`.
  - Returns `False` for no-scheme local paths.
- `uri_to_path(uri: str | Path) -> Path`
  - Returns a `Path` for local file URIs, absolute local paths, and relative local paths.
  - Accepts `file://localhost/path` as local.
  - Rejects non-local file authorities such as `file://server/share`.
  - Rejects file URIs with query or fragment because those are not local filesystem paths in v0.
  - Rejects non-file schemes such as `s3`, `gs`, `http`, and `https`.
  - Does not require the path to exist and does not make relative paths absolute.
- `path_to_file_uri(path: str | Path) -> str`
  - Requires an absolute local path.
  - Returns a quoted `file://` URI using the standard library.
  - Does not require existence, create files, expand `~`, or infer a base directory.
  - Round-trips spaces and percent-sensitive characters with `uri_to_path`.
- `normalize_uri(uri: str | Path, *, base_dir: str | Path | None = None) -> str`
  - Rejects empty and surrounding-whitespace string inputs.
  - Converts local file URIs to normalized `file://` URI strings.
  - Converts absolute no-scheme local paths to `file://` URI strings.
  - Returns a lexically normalized relative path string when input is relative and `base_dir is None`.
  - When input is relative and `base_dir` is supplied, resolves the relative path under `base_dir` and returns a `file://` URI.
  - Preserves non-file remote URIs exactly after invalid-input validation; it does not lowercase, quote, strip, or drop query/fragment details.

### Source Protocol And Local Source

- `DataSource` is a structural protocol in `loom.io.sources.base` and should be decorated with `@runtime_checkable`.
- Protocol shape:
  - `name: str`
  - `supports(self, uri: str | Path) -> bool`
  - `resolve(self, uri: str | Path) -> Path`
  - `open(self, uri: str | Path, mode: str = "rb", *, encoding: str = "utf-8") -> BinaryIO | TextIO`
  - `exists(self, uri: str | Path) -> bool`
  - `stat(self, uri: str | Path) -> Mapping[str, PlainData]`
  - `glob(self, pattern: str | Path) -> tuple[str, ...]`
- `LocalFileSystemSource` is a frozen slots dataclass:
  - `root: Path | None = None`
  - `name: str = "local"`
- `LocalFileSystemSource.__post_init__`
  - Validates `name` as a non-empty string.
  - Normalizes non-`None` `root` to an absolute `Path` with `Path(root).resolve(strict=False)`.
  - Does not create the root and does not restrict absolute inputs to remain under root.
- `supports(uri)` returns `True` for no-scheme local paths and local `file://` URIs, `False` for remote schemes, invalid/empty strings, non-local file authorities, and file URIs with query or fragment.
- `resolve(uri)`
  - Accepts no-scheme local paths and local `file://` URIs.
  - Applies `root` to relative no-scheme paths when `root` is set.
  - For relative paths with `root=None`, returns `Path(uri).resolve(strict=False)`, accepting the process-cwd dependency as documented debt.
  - Ignores `root` for absolute local paths and absolute file URIs.
  - Returns an absolute `Path` and does not require existence.
  - Raises `UnsupportedSourceOperationError` for unsupported schemes, non-local file authorities, or file URI query/fragment.
- `open(uri, mode="rb", *, encoding="utf-8")`
  - Supports exactly `rb`, `wb`, `rt`, and `wt`.
  - Text modes use UTF-8 by default through the `encoding` parameter.
  - Binary modes ignore `encoding`.
  - Wraps missing files in `SourceNotFoundError`.
  - Wraps permission failures in `SourcePermissionError`.
  - Wraps invalid modes and unsupported URI/source cases in `UnsupportedSourceOperationError`.
  - Wraps other local filesystem `OSError` failures in `DataSourceError`.
  - Does not create parent directories and does not perform atomic writes.
- `exists(uri)`
  - Returns `False` for missing local resources.
  - Raises `UnsupportedSourceOperationError` for unsupported schemes or non-local file URIs.
- `stat(uri)`
  - Raises `SourceNotFoundError` for missing paths.
  - Returns exactly these plain-data-compatible keys for existing local paths:
    - `uri`: normalized `file://` URI string for the resolved absolute path.
    - `backend`: source name, normally `local`.
    - `exists`: `True`.
    - `size_bytes`: integer `st_size`.
    - `mtime`: UTC timestamp string from `utc_timestamp(datetime.fromtimestamp(st_mtime, timezone.utc), timespec="seconds")`.
  - Does not compute checksums.
- `glob(pattern)`
  - Accepts no-scheme local glob patterns and local `file://` glob patterns.
  - Applies `root` to relative no-scheme patterns when `root` is set.
  - Ignores `root` for absolute patterns and file URI patterns.
  - Returns `tuple[str, ...]` of sorted normalized `file://` URI strings for all matched filesystem entries.
  - Does not decode file contents, compute checksums, or filter by artifact/resource type.

### Codec Protocol And Built-In Codecs

- `Codec` is a structural protocol in `loom.io.codecs.base` and should be decorated with `@runtime_checkable`.
- Protocol shape:
  - `key: str`
  - `encode(self, obj: object, *, metadata: Mapping[str, PlainData] | None = None) -> bytes`
  - `decode(self, data: bytes, *, metadata: Mapping[str, PlainData] | None = None) -> object`
- Built-in codec classes are frozen slots dataclasses unless a typing limitation appears.
- Built-in codec keys are exact and versioned:
  - `JSONCodec.key == "json.v1"`
  - `TextCodec.key == "text.v1"`
  - `BytesCodec.key == "bytes.v1"`
- Built-in codecs accept the optional `metadata` parameter for protocol compatibility. Phase 3 built-ins validate metadata as plain-data-compatible when supplied but do not interpret it.
- `JSONCodec.encode`
  - Calls `ensure_plain_data(obj, path="$")` before JSON serialization.
  - Must not call `to_plain_data` on caller input and must not convert dataclasses, `Path`, `datetime`, bytes, sets, callables, or arbitrary objects.
  - Serializes the validated plain data through `json_dumps_pretty(plain, sort_keys=True).encode("utf-8")`.
  - Wraps plain-data validation and JSON serialization failures in `CodecEncodeError`.
- `JSONCodec.decode`
  - Requires bytes input.
  - Decodes as UTF-8 with strict errors.
  - Parses through `json_loads(text, path="$")` and returns plain structured data only.
  - Wraps invalid input type, invalid UTF-8, invalid JSON, and non-plain parsed data in `CodecDecodeError`.
- `TextCodec`
  - Has an instance `encoding: str = "utf-8"` and validates it as a non-empty string.
  - Uses strict encoding/decoding errors.
  - Encodes only `str`; rejects non-string encode input with `CodecEncodeError`.
  - Decodes bytes to `str`; rejects non-bytes decode input with `CodecDecodeError`.
  - Does not call `str(obj)` and does not infer encodings from metadata.
- `BytesCodec`
  - Encodes only `bytes`, `bytearray`, and `memoryview`, normalizing all supported inputs to `bytes`.
  - Decodes only bytes-like input to `bytes`.
  - Rejects strings and arbitrary objects with codec-specific errors.

### Codec Registry

- `CodecRegistry` is an explicit instance class with no import-time mutable global registry.
- Constructor: `CodecRegistry(codecs: Iterable[Codec] = ())`.
  - Registers supplied codecs in order through `register`.
  - Rejects duplicates through the normal duplicate-registration path.
- `register(codec: Codec) -> None`
  - Validates that `codec.key` is a non-empty `str`.
  - Validates that `codec.encode` and `codec.decode` are callable.
  - Rejects duplicate keys with `CodecRegistrationError`.
  - Does not support `replace`, aliases, entry points, or plugin discovery in Phase 3.
- `get(key: str) -> Codec`
  - Returns the registered codec for an exact key.
  - Raises `UnknownCodecError` for unknown, empty, or non-string keys.
  - Error messages include the requested key and sorted registered keys.
- `keys() -> tuple[str, ...]`
  - Returns sorted codec keys.
- `encode(key: str, obj: object, *, metadata: Mapping[str, PlainData] | None = None) -> bytes`
  - Looks up the codec and dispatches `codec.encode`.
  - Propagates `CodecError` subclasses from the selected codec.
  - Wraps unexpected exceptions in `CodecEncodeError`.
- `decode(key: str, data: bytes, *, metadata: Mapping[str, PlainData] | None = None) -> object`
  - Looks up the codec and dispatches `codec.decode`.
  - Propagates `CodecError` subclasses from the selected codec.
  - Wraps unexpected exceptions in `CodecDecodeError`.
- `create_default_codec_registry() -> CodecRegistry`
  - Returns a fresh registry every call.
  - Registers new `JSONCodec`, `TextCodec`, and `BytesCodec` instances.
  - Tests must prove default registries do not share mutable state.

## Design Impact

This phase turns `loom.io` from an import-safe skeleton into the concrete byte/file boundary used by later stores and runtime stages. The main design impact is the separation of three responsibilities:

- URI helpers parse and normalize location strings without opening files.
- Sources open and inspect local bytes/text without decoding domain objects.
- Codecs encode and decode representation bytes without deciding artifact paths, run-store layout, checksums, or pipeline state.

The final plan intentionally keeps source lookup smaller than `docs/features/io.md`. A `SourceRegistry` can be added later when more than one source backend exists or when higher-level load helpers need source dispatch. Phase 3 still shapes `DataSource` and `LocalFileSystemSource` so that adding source dispatch later is additive.

## Future Compatibility

- Structural `DataSource` and `Codec` protocols let downstream packages provide compatible sources/codecs without subclassing `loom` internals.
- Versioned built-in codec keys (`json.v1`, `text.v1`, `bytes.v1`) keep future persisted refs understandable if codec behavior evolves.
- A fresh-instance default codec registry helper supports ergonomic setup while avoiding import-time plugin discovery and global test leakage.
- URI helpers preserve remote URI strings where safe, so future `s3://`, `gs://`, and `https://` routing can be added without replacing the parser.
- Returning plain-data-compatible `stat` metadata keeps future run-store and manifest persistence simple.
- Keeping atomic writes and checksums out of local source preserves Phase 7 ownership of durable store semantics.

## Alternatives Rejected

- Mutable global codec registry: rejected because it leaks state between tests/projects and conflicts with the explicit instance-based registry requirement.
- Source registry in Phase 3: rejected because only local filesystem support is in scope; a registry before multiple sources or load helpers exist would add review surface without acceptance value.
- Registry-level resource/artifact load helpers: rejected because they would combine source selection, reference semantics, and codec dispatch before stores own managed save/load behavior.
- Automatic codec inference from file extensions: rejected because v0 references use explicit codec keys and extension inference can be ambiguous.
- `JSONCodec` converting arbitrary Python objects with dataclass or `to_dict` hooks: rejected because serialization owns object-to-plain-data conversion and Phase 3 I/O should encode already-plain values only.
- Text codec calling `str(obj)`: rejected because silent conversion hides type bugs and can produce unstable output.
- Local source atomic writes or parent-directory creation: rejected because artifact stores own production-safe persistence and checksums in Phase 7.
- Remote storage dependencies or fsspec: rejected to keep Phase 3 standard-library only and within local-v0 scope.
- Exposing I/O from top-level `loom`: rejected because the canonical top-level public surface remains limited to cheap foundational primitives.

## Debt Introduced

- Only local filesystem source support is accepted for v0. Revisit when remote stores or source registries become a planned phase.
- `LocalFileSystemSource.resolve` may depend on process current working directory when no root is provided and the caller passes a relative path. Revisit if persisted references are accidentally created from unrooted relative paths. Callers that need reproducible persistence should pass `root` or use `normalize_uri(..., base_dir=...)`.
- Codec methods are byte-oriented and in-memory only. Revisit if large artifact tests show that streaming support is needed before post-v0 storage extensions.
- Source registry and resource/artifact load helpers are intentionally deferred. Revisit in Phase 7 only if local stores need shared dispatch helpers instead of direct source injection.
- Windows drive-letter and UNC handling is deferred. Revisit if CI or downstream tests begin targeting Windows local paths.

## Reviewability

The implementation PR should be a small, source-mirrored I/O PR. Reviewers should be able to inspect:

- URI behavior in `src/loom/io/uris.py` and unit tests.
- Local filesystem behavior in `src/loom/io/sources/local.py` and temp-directory tests.
- Codec encode/decode behavior in `src/loom/io/codecs/`.
- Duplicate, invalid, and unknown codec registry behavior.
- Error hierarchy and exception messages.
- Package import boundaries proving `loom.__init__`, primitives, and serialization do not import I/O.
- Absence of stores, config, pipeline execution, remote backends, plugin discovery, and domain-specific formats.

The PR should not include roadmap/status updates, PR-body files, feature broadening, or future-phase implementation.

## Files And Areas To Inspect

- `src/loom/io/__init__.py` for current skeleton exports and final public I/O imports.
- New URI/source/codec modules under `src/loom/io/`.
- `src/loom/errors.py` for the existing `IOErrorBase` root.
- `src/loom/ids.py` for the existing `CodecKey` alias.
- `src/loom/serialization/plain.py` for `PlainData`, `ensure_plain_data`, and unsupported value behavior.
- `src/loom/serialization/json.py` for deterministic JSON dump/load helpers.
- `src/loom/timestamps.py` for UTC `mtime` formatting.
- `src/loom/refs.py` and `src/loom/artifacts.py` only to ensure I/O does not add loading behavior to passive refs.
- `src/loom/__init__.py` and package import tests for cheap top-level import behavior.
- Existing tests under `tests/package/`, `tests/unit/loom/`, and `tests/unit/loom/serialization/`.
- `tests/README.md`, `Makefile`, `tools/test_harness/cli.py`, and `pyproject.toml` for suite names, markers, absent-suite behavior, and validation commands.
- Source references:
  - `docs/structure.md` sections "Source-Tree Boundary", "Target Source Tree", "Import and Dependency Shape", "I/O", "Runtime Dependency Policy", "Test Layout", and "Review Checklist".
  - `docs/loom.md` sections 4, 6.1, and 6.3.
  - `docs/features/io.md` sections 1 through 23, narrowed to the Phase 3 local source and generic codec scope.
  - `docs/features/artifacts.md` for the boundary between codec bytes and artifact-store-managed refs/checksums.
  - `docs/features/serialization.md` for plain-data and JSON ownership boundaries.
  - `docs/features/fingerprints.md` for checksum/fingerprint separation and the decision not to hash files in Phase 3.
  - `docs/features/testing.md` for suite responsibilities and extension contract tests.

## Implementation Steps

1. Add I/O error roots.
   - Implement `src/loom/io/errors.py`.
   - Implement source and codec error modules rooted in the same `LoomIOError` hierarchy.
   - Add concise messages with URI/path/key/operation context and exception chaining.
   - Tests: `tests/unit/loom/io/test_errors.py`.

2. Implement URI helpers.
   - Add `ParsedURI` and the six required helper functions in `src/loom/io/uris.py`.
   - Use standard-library parsing/quoting for URI behavior.
   - Lock down empty/whitespace rejection, file URI authority policy, remote preservation, relative path policy, absolute path URI conversion, and query/fragment rejection for local path conversion.
   - Tests: `tests/unit/loom/io/test_uris.py`.

3. Implement source protocol and local source.
   - Create `src/loom/io/sources/base.py`, `local.py`, `errors.py`, and `__init__.py`.
   - Define the runtime-checkable structural `DataSource` protocol.
   - Implement `LocalFileSystemSource` exactly as specified above.
   - Tests: `tests/unit/loom/io/sources/test_local.py` and source portions of `tests/contracts/test_data_source_contract.py`.

4. Implement codec protocol and generic codecs.
   - Create `src/loom/io/codecs/base.py`, `json_codec.py`, `text_codec.py`, `bytes_codec.py`, `errors.py`, and `__init__.py`.
   - Define the runtime-checkable structural `Codec` protocol.
   - Implement `JSONCodec`, `TextCodec`, and `BytesCodec` with accepted input types, UTF-8 behavior, metadata validation, and codec-specific error wrapping.
   - Tests: `tests/unit/loom/io/codecs/test_json_codec.py`, `test_text_codec.py`, and `test_bytes_codec.py`.

5. Implement codec registry.
   - Create `src/loom/io/codecs/registry.py`.
   - Implement explicit instance registration, lookup, sorted keys, encode/decode dispatch, duplicate rejection, invalid codec rejection, unknown lookup errors, and the fresh default-registry helper.
   - Do not add plugin discovery, entry-point loading, global registries, aliases, or source dispatch helpers.
   - Tests: `tests/unit/loom/io/codecs/test_registry.py` and codec portions of `tests/contracts/test_codec_contract.py`.

6. Update package exports and import-boundary tests.
   - Update only `loom.io` and its subpackage `__init__.py` files for Phase 3 public names.
   - Keep `loom.__init__` unchanged.
   - Extend package tests for `import loom.io`, public I/O imports, and import boundaries.
   - Tests: `tests/package/test_import.py`, `tests/package/test_public_api.py`, and `tests/package/test_import_boundaries.py`.

7. Add contract and integration coverage.
   - Create `tests/contracts/` and `tests/integration/` only because this phase introduces public extension protocols and cross-component source/codec cooperation.
   - Keep tests domain-neutral and temporary-directory only.
   - Tests: `tests/contracts/test_codec_contract.py`, `tests/contracts/test_data_source_contract.py`, and `tests/integration/test_io_basics.py`.

8. Run targeted checks during implementation.
   - Use focused direct pytest commands while iterating.
   - Run `make test-package`, `make test-unit`, `make test-contract`, and `make test-integration` before executor handoff when feasible.

9. Leave final PR validation to `loom_pr_preparer`.
   - `loom_pr_preparer` must run `make validate-pr` and `make test-summary`.
   - If network or cache permissions require `UV_CACHE_DIR=/tmp/uv-cache`, record that in the PR body and completion notes.

## Test Plan

### Package Suite

- Required for this phase.
- Existing suite target: `make test-package`.
- Expected paths:
  - `tests/package/test_import.py`
  - `tests/package/test_public_api.py`
  - `tests/package/test_import_boundaries.py`
- Required assertions:
  - `import loom` succeeds and retains the Phase 2 cheap top-level public surface exactly.
  - `import loom.io` succeeds and exposes the Phase 3 public I/O names.
  - `from loom.io import parse_uri, normalize_uri, LocalFileSystemSource, CodecRegistry, JSONCodec, TextCodec, BytesCodec` works.
  - `from loom.io.sources import DataSource, LocalFileSystemSource` works.
  - `from loom.io.codecs import Codec, CodecRegistry, create_default_codec_registry, JSONCodec, TextCodec, BytesCodec` works.
  - Top-level `import loom` does not eagerly import `loom.io`, config, pipeline, CLI, stores, plugins, optional remote backends, or downstream project packages.
  - `import loom.serialization`, `import loom.refs`, and `import loom.artifacts` do not import `loom.io`.
  - `loom.__all__` remains the Phase 2 list; no top-level I/O re-exports are added.

### Unit Suite

- Required for this phase.
- Existing suite target: `make test-unit`.
- Expected paths:
  - `tests/unit/loom/io/test_uris.py`
  - `tests/unit/loom/io/test_errors.py`
  - `tests/unit/loom/io/sources/test_local.py`
  - `tests/unit/loom/io/codecs/test_json_codec.py`
  - `tests/unit/loom/io/codecs/test_text_codec.py`
  - `tests/unit/loom/io/codecs/test_bytes_codec.py`
  - `tests/unit/loom/io/codecs/test_registry.py`
- Required assertions:
  - URI helpers parse and normalize `file://` URIs, absolute paths, and relative paths according to the contract.
  - URI helpers reject empty strings and surrounding whitespace.
  - `file://localhost/path` is local; `file://server/share` is rejected for local path conversion.
  - `path_to_file_uri` requires absolute paths and round-trips paths with spaces or percent-sensitive characters.
  - `uri_to_path` rejects unsupported remote schemes and file URI query/fragment.
  - `normalize_uri` resolves relative paths only when `base_dir` is supplied and preserves remote URI query/fragment details.
  - I/O, source, and codec errors inherit from the specified roots and messages include operation context.
  - `LocalFileSystemSource.supports`, `resolve`, `open`, `exists`, `stat`, and `glob` support local paths and local file URIs.
  - `LocalFileSystemSource.open` reads binary and UTF-8 text files, supports simple `wb` and `wt` write modes without creating parent directories, and wraps missing/invalid/permission operations in source errors.
  - `LocalFileSystemSource.stat` returns only plain-data-compatible metadata with normalized URI, backend, exists, size, and UTC mtime.
  - `LocalFileSystemSource.glob` returns deterministic sorted file URI strings.
  - `JSONCodec` round-trips plain structured values, produces deterministic pretty JSON bytes, and rejects unsupported non-plain objects such as dataclasses, paths, datetimes, bytes, sets, and arbitrary objects.
  - `JSONCodec.decode` wraps invalid input type, invalid UTF-8, and invalid JSON in `CodecDecodeError`.
  - `TextCodec` round-trips UTF-8 strings and rejects non-string encode input instead of calling `str()`.
  - `BytesCodec` round-trips bytes and normalizes bytearray/memoryview while rejecting arbitrary objects.
  - `CodecRegistry` registers structural codec instances, rejects duplicate keys, rejects invalid codec objects, lists keys deterministically, dispatches encode/decode, and raises unknown lookup errors that include available keys.
  - `create_default_codec_registry()` returns a fresh registry with exactly `bytes.v1`, `json.v1`, and `text.v1` sorted from `keys()`.

### Contract Suite

- Required for this phase because Phase 3 introduces public extension protocols.
- Existing suite target: `make test-contract`.
- The directory is currently absent; implementation must create it with Phase 3 contract tests.
- Expected paths:
  - `tests/contracts/test_codec_contract.py`
  - `tests/contracts/test_data_source_contract.py`
- Required assertions:
  - A downstream-style codec object satisfying the `Codec` protocol without inheriting from a `loom` base class can be registered and used through `CodecRegistry`.
  - Built-in `JSONCodec`, `TextCodec`, and `BytesCodec` satisfy the `Codec` protocol structurally.
  - A downstream-style source object satisfying the `DataSource` protocol without inheritance can be treated as a data source by runtime smoke tests.
  - `LocalFileSystemSource` satisfies the `DataSource` protocol structurally.
  - Contract tests remain domain-neutral and use only temporary files and dummy values.

### Integration Suite

- Required as a small cross-component check because this phase combines sources and codecs but does not yet have stores.
- Existing suite target: `make test-integration`.
- The directory is currently absent; implementation must create it with the Phase 3 integration test.
- Expected path:
  - `tests/integration/test_io_basics.py`
- Required assertions:
  - JSON, text, and bytes payloads can be encoded through a codec registry, written through `LocalFileSystemSource.open(..., "wb")`, read through `LocalFileSystemSource.open(..., "rb")`, and decoded through the same registry.
  - `LocalFileSystemSource.glob` over files written in the integration test returns sorted normalized file URIs suitable for later manifest construction.
  - Passive `ResourceRef` and `ArtifactRef` values are not given `open`, `load`, `save`, `exists`, or source/codec dispatch methods as part of the integration path.

### E2E Suite

- Deferred for this phase.
- Existing suite target: `make test-e2e`.
- Expected path status: `tests/e2e` may remain absent or contain no tests.
- Expected command behavior: the harness may report `not present`.
- Reason: Phase 3 has no config composition, pipeline parser, runner, stores, CLI path, or complete user-visible workflow. End-to-end pipeline behavior begins after config, stores, planning, and execution exist.
- If unrelated e2e tests exist by the time Phase 3 is implemented, PR preparation should run the target and document pass/fail status without adding new Phase 3 e2e scope.

### Opt-In Suites

- Deferred for this phase.
- Markers affected: `slow`, `slurm`, `network`, and `optional_dependency`.
- Reason: Phase 3 intentionally excludes remote sources, network access, optional storage dependencies, SLURM, subprocess execution, large artifacts, and slow tests.
- No opt-in network, remote-store, Windows-specific, slow, or optional-dependency suite is required.
- If an opt-in check is introduced later, PR preparation should document why it is not relevant to this local standard-library phase.

## Risks

- URI normalization can accidentally make relative paths depend on process current working directory. Mitigation: keep `parse_uri` relative-path preserving, require `base_dir` for `normalize_uri` absolute conversion, and test root/base behavior explicitly.
- `file://` parsing can mishandle quoted characters or authorities. Mitigation: use standard-library URL parsing/quoting and test spaces, percent-sensitive characters, `localhost`, non-local authorities, query, and fragment.
- JSON codec could blur serialization and I/O by accepting arbitrary objects. Mitigation: require `ensure_plain_data` and test dataclass/path/datetime/bytes/set rejection.
- Local source write support could be mistaken for artifact-store-safe persistence. Mitigation: document and test that it is simple open/truncate behavior only; Phase 7 owns atomic writes and checksums.
- Registry errors can degrade to plain `KeyError` or hidden duplicates. Mitigation: unit-test duplicate registration, invalid codec registration, and unknown lookup messages.
- Adding contract and integration suites may expose pre-existing harness assumptions because those directories are currently absent. Mitigation: use the existing Make targets; the harness already supports these suites.
- Text encoding choices can become ambiguous if metadata overrides are interpreted too early. Mitigation: Phase 3 `TextCodec` uses its instance encoding, UTF-8 by default, and does not infer encoding from metadata.

## Validation Commands

Targeted development commands for the implementation agent:

```sh
make test-package
make test-unit
make test-contract
make test-integration
uv run pytest tests/unit/loom/io
uv run pytest tests/contracts/test_codec_contract.py tests/contracts/test_data_source_contract.py
uv run pytest tests/integration/test_io_basics.py
```

Final PR-preparation commands for `loom_pr_preparer`:

```sh
make validate-pr
make test-summary
```

`make validate-pr` is expected to run Ruff, Pyright, default Pytest, and build checks. `make test-summary` is expected to write suite-level evidence for the PR body. If network or cache permissions require `UV_CACHE_DIR=/tmp/uv-cache`, PR preparation should use that environment setting and record it.

## Executor Handoff Notes

Safe implementation slices for `loom_phase_executor`:

1. URI and error slice.
   - Owns `src/loom/io/errors.py`, `src/loom/io/uris.py`, and `tests/unit/loom/io/test_uris.py` plus `test_errors.py`.
   - Public choices fixed: no remote path conversion, no relative path resolution without `base_dir`, no query/fragment local path conversion.

2. Local source slice.
   - Owns `src/loom/io/sources/*`, `tests/unit/loom/io/sources/test_local.py`, and `tests/contracts/test_data_source_contract.py`.
   - Public choices fixed: no `SourceRegistry`, no root containment policy, no parent directory creation, no atomic writes, no checksums.

3. Codec slice.
   - Owns `src/loom/io/codecs/base.py`, built-in codec modules, codec errors, and codec unit tests.
   - Public choices fixed: `JSONCodec` uses `ensure_plain_data`, `TextCodec` rejects non-strings, `BytesCodec` handles bytes-like values only, metadata is validated but not interpreted by built-ins.

4. Registry slice.
   - Owns `src/loom/io/codecs/registry.py`, registry tests, and codec contract tests.
   - Public choices fixed: instance-based only, no replacement option, no aliases, no entry points, no mutable global default registry.

5. Export, package, and integration slice.
   - Owns `src/loom/io/__init__.py`, subpackage exports, package tests, and `tests/integration/test_io_basics.py`.
   - Public choices fixed: no top-level `loom` I/O re-exports, no source/load helpers, no passive-ref loading methods.

Implementation choices that must not be revisited by the executor:

- Keep Phase 3 standard-library only.
- Keep `create_default_codec_registry()` in scope and fresh-instance only.
- Keep `SourceRegistry`, source dispatch helpers, artifact stores, checksums, config behavior, pipeline behavior, remote backends, and domain codecs out of scope.
- Keep `loom.__init__` unchanged unless an existing package test exposes a direct blocker.
- Stop and report a blocker if a public API or suite obligation cannot be implemented within this contract.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-03 by `loom_phase_refiner` for the bounded post-implementation validation pass.
- PR review: unused.

The plan quality gate budget for the canonical v0 plan is already fully used and passed with no remaining blockers. The implementation refinement budget is now consumed; do not run another automated implementation refinement pass for Phase 3 unless the manager receives explicit user instruction. The PR-review budget remains unused.

## Completion Notes

- Draft plan committed by `loom_phase_planner`: `9b05db8 plan: add phase plan`.
- Final expanded plan committed by `loom_phase_plan_expander`: `7849c72 plan: refine io basics phase plan`.
- Implementation summary:
  - Implemented the complete Phase 3 I/O surface under `src/loom/io` with concrete URI helpers, source protocol + local filesystem source, codec protocol + JSON/text/bytes codecs, codec registry, and package exports.
  - Added explicit error hierarchies for URI/source/codec failures and kept phase boundary constraints (standard-library only, no stores, no config/pipeline behavior).
  - Added and aligned package/unit/contract/integration tests:
    - `tests/unit/loom/io/codecs/test_*.py`
    - `tests/unit/loom/io/sources/test_local.py`
    - `tests/unit/loom/io/test_io_errors.py`
    - `tests/unit/loom/io/test_uris.py`
    - `tests/contracts/test_codec_contract.py`
    - `tests/contracts/test_data_source_contract.py`
    - `tests/integration/test_io_basics.py`
    - `tests/package/test_import.py`
    - `tests/package/test_public_api.py`
    - `tests/package/test_import_boundaries.py`
  - `make test-package`, `make test-unit`, `make test-contract`, and `make test-integration` were executed and passed after adjusting the io error test module name to avoid pytest import collision.
- Implementation refinement summary:
  - Fixed validation-blocking Ruff findings by removing unused codec/test imports and adding the missing `PlainData` import for `JSONCodec` annotations.
  - Aligned `LocalFileSystemSource.exists()` with the finalized source contract: missing local resources return `False`, while unsupported remote schemes, non-local file authorities, and file URI query/fragment cases raise `UnsupportedSourceOperationError`.
  - Added focused unit coverage for the unsupported `exists()` cases.
  - Resolved Phase 3 Pyright failures exposed by `make validate-pr` by adding mode-specific source `open()` overloads, preserving bytes-like `BytesCodec.decode()` behavior in its public type, and tightening codec test protocol annotations.
- Validation evidence:
  - `make test-package`: passed
  - `make test-unit`: passed
  - `make test-contract`: passed
  - `make test-integration`: passed
  - Targeted run used: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/io tests/contracts tests/integration` also passed.
  - Refinement targeted run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/io tests/contracts tests/integration` passed with 57 tests.
  - Refinement lint/type checks: `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` passed; `UV_CACHE_DIR=/tmp/uv-cache uv run pyright` passed with 0 errors.
  - Refinement PR gate: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed, including Ruff, Pyright, default pytest (136 passed), and `uv build`.
  - Final PR-prep gate: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed on 2026-05-03; Ruff passed, Pyright reported 0 errors, default pytest passed with 136 tests, and `uv build` produced source and wheel distributions.
  - Final PR-prep suite summary: `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed on 2026-05-03 and wrote `build/test-summary.md`; package passed with 11 tests, unit passed with 119 tests, contract passed with 4 tests, integration passed with 2 tests, and e2e was not present as deferred.
- PR body: prepared at `docs/phases/add-io-basics-pr-body.md`.
- PR: not opened.
- PR creation blocker:
  - `git push -u origin codex/add-io-basics` failed after network escalation with `ssh_askpass: exec(/usr/bin/ssh-askpass): No such file or directory`, `git@github.com: Permission denied (publickey).`, and `fatal: Could not read from remote repository.`
  - `gh pr create --base develop --head codex/add-io-basics --title "Phase 3: I/O Basics" --body-file docs/phases/add-io-basics-pr-body.md` failed with `pull request create failed: GraphQL: Head sha can't be blank, Base sha can't be blank, No commits between develop and codex/add-io-basics, Head ref must be a branch (createPullRequest)`.
- Remaining blockers: remote PR creation is unavailable until `codex/add-io-basics` can be pushed or created on GitHub.
