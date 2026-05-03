# Phase 3 Expanded Plan: I/O Basics

## Metadata

- Status: draft expanded plan.
- Branch: `codex/add-io-basics`.
- Worktree: `/home/samcantrill/work/loom-worktrees/add-io-basics`.
- Expanded plan path: `docs/phases/add-io-basics.md`.
- Full plan: `docs/implementation-plans/implementation-plan-v0.md`.
- Source phase: `Phase 3 - I/O Basics`.
- Base branch: local `develop` at `3a3eb4f253617d13f0d74ddfd51742574e785db6` (`docs: mark phase 2 merged`).
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no remaining blockers are recorded in the canonical v0 plan.
- Plan quality gate loop budget: initial plan review used, automated plan refinement pass used, confirmation review used.
- Setup limitation: manager preflight recorded that `git fetch origin develop` and `git push origin develop` are unavailable in this environment because SSH public-key authentication and `ssh_askpass` are not configured. Per the planning prompt and manager instruction, this branch and worktree were created from local `develop`.
- Worktree creation note: the first sandboxed `git worktree add` attempt could not write repository refs because `.git/refs` was read-only in the sandbox; the approved rerun created the required branch and worktree. This is an environment limitation, not a product blocker.
- Prior phase state: Phase 1 and Phase 2 are recorded as merged locally in the canonical plan. Phase 3 remains pending at draft-plan time.
- Blockers: none.

## Objective

Implement the first real `loom.io` layer: local URI helpers, local filesystem access, generic JSON/text/bytes codecs, codec-specific errors, and an explicit instance-based codec registry.

The phase must keep I/O as the bridge between plain serialized data and stored bytes. Serialization owns Python-object to plain-data conversion; stores own artifact path allocation, atomic writes, checksums, run layout, and artifact indexes.

## Full-Plan Context

The v0 implementation plan builds `loom` as a typed, domain-neutral runtime in small phases. Phase 1 created import-safe package skeletons, broad error roots, timestamp/id helpers, and import-boundary guardrails. Phase 2 implemented primitives, provenance, fingerprints, and serialization helpers, including `ResourceRef`, `ArtifactRef`, `CodecKey`, `PlainData`, `ensure_plain_data`, `json_loads`, and deterministic JSON helpers.

Phase 3 is the first behavior-bearing I/O phase. Later phases depend on it as follows:

- Phase 4 config composition must remain independent from I/O and must not gain filesystem persistence behavior.
- Phase 5 recipes and instantiation may create or configure codec instances, but recipe catalogs and target imports are out of this phase.
- Phase 7 local stores will use codecs and local filesystem access for managed artifact save/load, checksum calculation, manual registration, and run layout persistence.
- Phase 8 planning/resume will rely on stores for checksum validation and must not compute resume policy in the I/O layer.
- Phase 9 local execution will receive store-backed artifact helpers; stages still should not make `ResourceRef` or `ArtifactRef` value objects load themselves.

Controlling constraints:

- Keep `loom` domain-neutral; no dataset, model, array, image, video, report, checkpoint, or table-specific codecs.
- Keep runtime dependencies empty and standard-library only until Phase 4 introduces hard config dependencies.
- Preserve import direction from `docs/structure.md`: primitives and serialization do not import I/O; I/O does not import pipeline runners, stores, config composition, CLI, plugins, optional remote backends, or downstream project packages.
- Keep `loom.__init__` cheap and unchanged unless a package import-boundary test exposes a documented Phase 3 blocker.
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

## In-Scope Work

- Replace the empty `src/loom/io/__init__.py` skeleton with stable Phase 3 exports for URI helpers, source/codec protocols, local source, generic codecs, registry helpers, and I/O errors.
- Add `src/loom/io/errors.py`.
  - Define `LoomIOError(IOErrorBase)` and `UnsupportedURIError`.
  - Re-export source and codec error roots only if doing so avoids duplicate incompatible classes.
  - Keep concrete source errors in `loom.io.sources.errors` and concrete codec errors in `loom.io.codecs.errors`.
- Add `src/loom/io/uris.py`.
  - Define a small frozen `ParsedURI` dataclass.
  - Implement `parse_uri`, `get_uri_scheme`, `is_file_uri`, `uri_to_path`, `path_to_file_uri`, and `normalize_uri`.
  - Support `file:///absolute/path`, absolute local paths, and relative local paths.
  - Support `file://localhost/path` as local; reject non-local file authorities such as `file://server/share`.
  - Reject empty URI strings and strings with surrounding whitespace rather than silently stripping them.
  - Keep relative path base resolution caller-owned; `normalize_uri` resolves relative paths only when `base_dir` is provided.
  - Preserve non-file remote URIs in `parse_uri` and `normalize_uri` where safe, but do not convert them to paths or open them.
- Add `src/loom/io/sources/`.
  - `base.py` defines `DataSource` as a structural protocol.
  - `local.py` defines `LocalFileSystemSource` as the only concrete Phase 3 source.
  - `errors.py` defines `DataSourceError`, `SourceNotFoundError`, `SourcePermissionError`, and `UnsupportedSourceOperationError`.
  - `__init__.py` re-exports the protocol, local source, and source errors.
- Implement `LocalFileSystemSource`.
  - Use a frozen dataclass with optional `root: Path | None = None` and `name: str = "local"`.
  - Support no-scheme local paths and `file://` URIs.
  - `supports(uri)` returns true for local/no-scheme paths and `file` URIs, false for remote schemes.
  - `resolve(uri)` returns an absolute `Path` after applying `root` to relative paths. It does not require the path to exist.
  - `open(uri, mode="rb", *, encoding="utf-8")` supports exactly `rb`, `wb`, `rt`, and `wt`. Text modes use UTF-8 by default. It wraps missing files, permission failures, and invalid modes in source-specific errors with URI/path context. It does not create parent directories and does not perform atomic writes.
  - `exists(uri)` returns `False` for missing local resources and wraps unsupported URI schemes as source errors.
  - `stat(uri)` returns plain-data-compatible metadata for existing files: normalized `file://` URI, backend name, `exists: True`, `size_bytes`, and UTC `mtime`. Missing files raise `SourceNotFoundError`.
  - `glob(pattern)` resolves the pattern against `root` when appropriate, returns deterministic sorted `file://` URI strings, and does not decode file contents.
- Add `src/loom/io/codecs/`.
  - `base.py` defines `Codec` as a structural protocol with `key`, `encode`, and `decode`.
  - `json_codec.py` defines `JSONCodec`.
  - `text_codec.py` defines `TextCodec`.
  - `bytes_codec.py` defines `BytesCodec`.
  - `registry.py` defines `CodecRegistry` and `create_default_codec_registry`.
  - `errors.py` defines `CodecError`, `CodecRegistrationError`, `UnknownCodecError`, `CodecEncodeError`, and `CodecDecodeError`.
  - `__init__.py` re-exports the codec protocol, concrete codecs, registry, helper, and codec errors.
- Implement generic codecs.
  - `JSONCodec.key` is `json.v1`.
  - `JSONCodec.encode` accepts only plain-data-compatible values by using `ensure_plain_data`; it must not call conversion hooks that reconstruct or serialize arbitrary Python objects for callers. It serializes deterministic UTF-8 JSON bytes through the existing serialization JSON helpers.
  - `JSONCodec.decode` parses UTF-8 JSON bytes through `json_loads` and returns plain structured data only.
  - `TextCodec.key` is `text.v1`; it encodes only `str`, decodes bytes as UTF-8 by default, and rejects non-string encode inputs instead of silently calling `str()`.
  - `BytesCodec.key` is `bytes.v1`; it accepts `bytes`, `bytearray`, and `memoryview` on encode, normalizes them to `bytes`, and decodes to `bytes`.
  - Built-in codecs should wrap encode/decode failures in codec-specific errors that include the codec key and operation.
- Implement `CodecRegistry`.
  - The registry is instance-based with no mutable import-time global registry.
  - `register(codec)` validates a non-empty string `codec.key`, structural `encode`/`decode` callables, and rejects duplicate keys.
  - `get(key)` returns a codec instance or raises `UnknownCodecError` with the requested key and deterministic list of registered keys.
  - `keys()` returns sorted codec keys.
  - `encode(key, obj, *, metadata=None)` and `decode(key, data, *, metadata=None)` dispatch through the selected codec.
  - `create_default_codec_registry()` returns a fresh registry containing new `JSONCodec`, `TextCodec`, and `BytesCodec` instances.
- Add package, unit, contract, and small integration tests for the behavior introduced in this phase.

## Out-of-Scope Work

- No `SourceRegistry`, default source registry, source plugin discovery, source replacement policy, or automatic source lookup by URI scheme. The local source protocol and class should leave room for this later without implementing it now.
- No `load_resource`, `load_artifact`, `read_uri_bytes`, `write_uri_bytes`, or registry-level resource/artifact loading helpers.
- No artifact-store layout, local artifact store, run store, atomic write helpers, run status files, artifact indexes, checksum validation policy, or store-managed save/load behavior.
- No file or stream checksum helpers in I/O unless the plan expansion agent determines one is strictly required for `stat`; by default Phase 7 owns checksum computation for stored artifacts.
- No remote sources, HTTP/S3/GCS/Azure support, fsspec dependency, network access, package-resource source, database-backed resources, or optional backend extras.
- No domain codecs for arrays, dataframes, images, videos, model checkpoints, metrics, reports, compressed formats, pickle, YAML, or unsafe loaders.
- No automatic codec inference from file extensions, resource types, artifact types, or URI suffixes.
- No config composition, recipe expansion, target instantiation, config-driven codec construction, or hard config dependencies.
- No pipeline specs, stage contexts, runner behavior, execution, resume planning, selectors, or CLI behavior.
- No top-level `loom.__init__` I/O re-exports unless a documented import-boundary requirement is discovered during plan expansion.
- No updates to the canonical implementation-plan phase status, PR body creation, broad validation runs, PR opening, remote pushes, or implementation code during this planning stage.

## Assumptions

- Local `develop` at `3a3eb4f253617d13f0d74ddfd51742574e785db6` is the manager-approved Phase 3 base because remote synchronization is unavailable in this environment.
- POSIX local filesystem behavior is the primary v0 target. Windows drive-letter and UNC path behavior are deferred unless existing tests already require them.
- URI helper functions accept `str | Path` where that is natural for path conversion, but persisted public references remain URI strings.
- `path_to_file_uri` requires an absolute local path and uses standard-library URI quoting. Callers must resolve relative paths explicitly before converting them to persisted file URIs.
- `uri_to_path` accepts file URIs, absolute paths, and relative paths, and rejects remote schemes with `UnsupportedURIError`.
- `normalize_uri` returns a `file://` URI for file URIs and absolute local paths. For relative local paths, it returns a normalized relative path unless `base_dir` is supplied, in which case it returns a `file://` URI for the resolved absolute path.
- `LocalFileSystemSource.resolve` may turn relative paths into absolute paths using `root` or the process current working directory. URI parsing itself must not do that global resolution.
- `LocalFileSystemSource.glob` returns normalized `file://` URI strings, not `Path` objects, because glob output is likely to feed manifests and later persisted refs.
- `stat` metadata must stay plain-data-compatible; no raw `os.stat_result`, `Path`, or `datetime` objects should escape the public API.
- Built-in codec methods operate on in-memory bytes. Streaming codec protocols are deferred.
- `JSONCodec` should not accept dataclasses, `Path`, `datetime`, bytes, sets, callables, or arbitrary objects through `to_plain_data`; callers must convert those to plain data before passing them to I/O.
- The codec registry owns registration and dispatch only. It does not select sources, construct refs, compute checksums, update run indexes, or manage default global state.
- `create_default_codec_registry()` is acceptable because it returns a fresh instance every call and does not introduce global mutable state.

## Design Impact

This phase turns the `loom.io` package from an import-safe skeleton into the concrete byte/file boundary used by later stores and runtime stages. The main design impact is the separation of three responsibilities:

- URI helpers parse and normalize location strings without opening files.
- Sources open and inspect bytes/text at local filesystem locations without decoding domain objects.
- Codecs encode and decode representation bytes without deciding artifact paths, run-store layout, checksums, or pipeline state.

The plan intentionally keeps source lookup smaller than the broader feature document. A `SourceRegistry` can be added when more than one source backend exists or when load helpers need source dispatch. Phase 3 should still shape `DataSource` and `LocalFileSystemSource` so that adding a source registry later is additive rather than a breaking redesign.

## Future Compatibility

- Structural `DataSource` and `Codec` protocols let downstream packages provide compatible sources/codecs without subclassing `loom` internals.
- Versioned built-in codec keys (`json.v1`, `text.v1`, `bytes.v1`) keep future persisted refs understandable if codec behavior evolves.
- A fresh-instance default codec registry helper supports ergonomic setup while avoiding import-time plugin discovery and global test leakage.
- Local URI helpers preserve remote URI details where safe, so future remote source registries can route `s3://`, `gs://`, or `https://` without changing the parser.
- Returning plain-data-compatible `stat` metadata keeps future run-store and manifest persistence simple.
- Keeping atomic writes and checksums out of local source preserves Phase 7 ownership of durable store semantics.

## Alternatives Rejected

- Mutable global codec registry: rejected because it is hard to test, leaks state between projects, and conflicts with the explicit instance-based registry requirement.
- Source registry in Phase 3: rejected because only local filesystem support is in scope; adding a registry before multiple sources or load helpers exist would add review surface without acceptance value.
- Automatic codec inference from file extensions: rejected because v0 references use explicit codec keys and extension inference can be ambiguous.
- `JSONCodec` converting arbitrary Python objects with dataclass or `to_dict` hooks: rejected because serialization owns object-to-plain-data conversion and Phase 3 I/O should encode already-plain values.
- Text codec calling `str(obj)`: rejected because silent conversion hides type bugs and can produce unstable output.
- Local source atomic writes: rejected because artifact stores own production-safe persistence and checksums in Phase 7.
- Remote storage dependencies or fsspec: rejected to keep Phase 3 standard-library only and within the local-v0 scope.
- Exposing I/O from top-level `loom`: rejected for this phase because the canonical top-level public surface remains limited to cheap foundational primitives.

## Debt Introduced

- Only local filesystem source support is accepted for v0. Revisit when remote stores or source registries become a planned phase.
- `LocalFileSystemSource.resolve` may depend on process current working directory when no root is provided and the caller passes a relative path. Revisit if persisted references are accidentally created from unrooted relative paths; callers that need reproducible persistence should pass `root` or use `normalize_uri(..., base_dir=...)`.
- Codec methods are byte-oriented and in-memory only. Revisit if large artifact tests show that streaming support is needed before post-v0 storage extensions.
- Source registry and resource/artifact load helpers are intentionally deferred. Revisit in Phase 7 if local stores need shared dispatch helpers instead of direct source injection.

## Reviewability

The implementation PR should be a small, source-mirrored I/O PR. Reviewers should be able to inspect:

- URI behavior in `src/loom/io/uris.py` and unit tests;
- local filesystem behavior in `src/loom/io/sources/local.py` and temp-directory tests;
- codec encode/decode behavior in `src/loom/io/codecs/`;
- duplicate/unknown codec registry behavior;
- error hierarchy and exception messages;
- package import boundaries proving `loom.__init__`, primitives, and serialization do not import I/O; and
- absence of stores, config, pipeline execution, remote backends, plugin discovery, and domain-specific formats.

The PR should not include roadmap/status updates, PR-body files, feature broadening, or future-phase implementation.

## Files And Areas To Inspect

- `src/loom/io/__init__.py` for current skeleton exports and final public I/O imports.
- New URI/source/codec modules under `src/loom/io/`.
- `src/loom/errors.py` for the existing `IOErrorBase` root.
- `src/loom/ids.py` for the existing `CodecKey` alias.
- `src/loom/serialization/plain.py` for `PlainData`, `ensure_plain_data`, and unsupported value behavior.
- `src/loom/serialization/json.py` for deterministic JSON dump/load helpers.
- `src/loom/refs.py` and `src/loom/artifacts.py` only to ensure I/O does not add loading behavior to passive refs.
- `src/loom/__init__.py` and package import tests for cheap top-level import behavior.
- Existing tests under `tests/package/`, `tests/unit/loom/`, and `tests/unit/loom/serialization/`.
- `tests/README.md`, `Makefile`, and `pyproject.toml` for suite names, markers, and validation commands.
- Source references:
  - `docs/structure.md` sections "Source-Tree Boundary", "Target Source Tree", "Import and Dependency Shape", "I/O", "Runtime Dependency Policy", "Test Layout", and "Review Checklist".
  - `docs/loom.md` sections 4, 6.1, and 6.3.
  - `docs/features/io.md` sections 1 through 30, narrowed to the Phase 3 local source and generic codec scope.
  - `docs/features/artifacts.md` only for the boundary between codec bytes and artifact-store-managed refs/checksums.
  - `docs/features/serialization.md` for plain-data and JSON ownership boundaries.
  - `docs/features/fingerprints.md` for checksum/fingerprint separation and the decision not to hash files in Phase 3.
  - `docs/features/testing.md` for suite responsibilities and extension contract tests.

## Implementation Steps

1. Add I/O error roots.
   - Implement `src/loom/io/errors.py` with `LoomIOError(IOErrorBase)` and `UnsupportedURIError`.
   - Add source and codec error modules rooted in the same `LoomIOError` hierarchy without creating duplicate incompatible roots.
   - Make messages concise but include URI, path, key, operation, or registered keys where relevant.

2. Implement URI helpers.
   - Add `ParsedURI` as a frozen slots dataclass with `raw`, `scheme`, `path`, `authority`, `query`, and `fragment`.
   - Implement scheme extraction using standard-library parsing while treating no-scheme local paths as local paths.
   - Implement file URI validation for local POSIX file URIs, including quoting/unquoting and `localhost`.
   - Implement conversion and normalization behavior named in the assumptions.
   - Add path-aware unsupported URI errors for remote path conversion attempts.

3. Implement source protocol and local source.
   - Create `src/loom/io/sources/base.py`, `local.py`, `errors.py`, and `__init__.py`.
   - Define the structural `DataSource` protocol.
   - Implement `LocalFileSystemSource` against the URI helpers.
   - Ensure all public metadata from `stat` is plain-data-compatible.
   - Keep write behavior simple and non-atomic.

4. Implement codec protocol and generic codecs.
   - Create `src/loom/io/codecs/base.py`, `json_codec.py`, `text_codec.py`, `bytes_codec.py`, `errors.py`, and `__init__.py`.
   - Define the narrow `Codec` protocol using `encode` and `decode` bytes methods.
   - Implement `JSONCodec`, `TextCodec`, and `BytesCodec` with the accepted input types and error wrapping described above.
   - Keep codec metadata optional and plain-data-compatible; built-in codecs do not need rich metadata behavior in this phase.

5. Implement codec registry.
   - Create `src/loom/io/codecs/registry.py`.
   - Implement explicit instance registration, lookup, sorted keys, encode dispatch, decode dispatch, duplicate rejection, and unknown lookup errors.
   - Add `create_default_codec_registry()` returning a fresh registry populated with the three built-in codecs.
   - Do not add plugin discovery, entry-point loading, global registries, aliases, or source dispatch helpers.

6. Update package exports.
   - Update `src/loom/io/__init__.py` and subpackage `__init__.py` files to export only implemented Phase 3 public names.
   - Do not update top-level `src/loom/__init__.py` unless required to preserve existing Phase 2 public exports or import-boundary tests.

7. Add package, unit, contract, and integration coverage.
   - Place source-mirrored unit tests under `tests/unit/loom/io/`.
   - Add contract tests for structural codec/source compatibility under `tests/contracts/`.
   - Add one small integration test under `tests/integration/` for local source plus codec registry cooperation.
   - Update package import-boundary tests to protect I/O import behavior.

8. Run targeted checks during implementation.
   - Run direct pytest commands for changed test files while iterating.
   - Run `make test-package`, `make test-unit`, `make test-contract`, and `make test-integration` before handoff when feasible.

9. Leave final PR validation to `loom_pr_preparer`.
   - Before PR preparation, run `make validate-pr`.
   - Before PR preparation, run `make test-summary`.

## Test Plan

### Package Suite

- Required for this phase.
- Expected paths:
  - `tests/package/test_import.py`
  - `tests/package/test_public_api.py`
  - `tests/package/test_import_boundaries.py`
- Required assertions:
  - `import loom` succeeds and retains the Phase 2 cheap top-level public surface.
  - `import loom.io` succeeds and exposes Phase 3 public I/O names.
  - `from loom.io import parse_uri, normalize_uri, LocalFileSystemSource, CodecRegistry, JSONCodec, TextCodec, BytesCodec` works.
  - Importing `loom.io` does not import pipeline execution, stores, config composition, CLI, plugin discovery, optional remote backends, or downstream project packages.
  - `loom.refs`, `loom.artifacts`, and `loom.serialization` do not import `loom.io`.
- Targeted command: `make test-package`.

### Unit Suite

- Required for this phase.
- Expected paths:
  - `tests/unit/loom/io/test_uris.py`
  - `tests/unit/loom/io/test_errors.py`
  - `tests/unit/loom/io/sources/test_local.py`
  - `tests/unit/loom/io/codecs/test_json_codec.py`
  - `tests/unit/loom/io/codecs/test_text_codec.py`
  - `tests/unit/loom/io/codecs/test_bytes_codec.py`
  - `tests/unit/loom/io/codecs/test_registry.py`
- Required assertions:
  - URI helpers parse and normalize `file://` URIs, absolute paths, and relative paths according to the phase policy.
  - `path_to_file_uri` requires absolute paths and round-trips paths with spaces or quoted characters.
  - `uri_to_path` rejects unsupported remote schemes.
  - `normalize_uri` resolves relative paths only when `base_dir` is supplied.
  - `LocalFileSystemSource.open` reads binary and UTF-8 text files, supports simple write modes, and wraps missing/invalid operations in source errors.
  - `LocalFileSystemSource.exists`, `stat`, `glob`, and `resolve` behave deterministically and return plain-data-compatible metadata or URI strings.
  - `JSONCodec` round-trips plain structured values, produces deterministic JSON bytes, and rejects unsupported non-plain objects such as datetimes, paths, bytes, sets, and arbitrary objects.
  - `JSONCodec` decode wraps invalid UTF-8 or invalid JSON in codec decode errors.
  - `TextCodec` round-trips strings with UTF-8 and rejects non-string encode input.
  - `BytesCodec` round-trips bytes and normalizes bytearray/memoryview while rejecting arbitrary objects.
  - `CodecRegistry` registers structural codec instances, rejects duplicate keys, rejects invalid codec objects, lists keys deterministically, dispatches encode/decode, and raises unknown lookup errors that include available keys.
- Targeted command: `make test-unit`.

### Contract Suite

- Required for this phase because Phase 3 introduces public extension protocols.
- Expected paths:
  - `tests/contracts/test_codec_contract.py`
  - `tests/contracts/test_data_source_contract.py`
- Required assertions:
  - A downstream-style codec object satisfying the `Codec` protocol without inheriting from a `loom` base class can be registered and used through `CodecRegistry`.
  - A downstream-style source object satisfying the `DataSource` protocol without inheritance can be treated as a data source by type checkers and runtime smoke tests.
  - Built-in `JSONCodec`, `TextCodec`, `BytesCodec`, and `LocalFileSystemSource` satisfy their protocols structurally.
  - The contract tests remain domain-neutral and use only temporary files and dummy values.
- Targeted command: `make test-contract`.

### Integration Suite

- Required as a small cross-component check because this phase combines sources and codecs but does not yet have stores.
- Expected path:
  - `tests/integration/test_io_basics.py`
- Required assertions:
  - A JSON/text/bytes payload can be encoded through a codec registry, written through `LocalFileSystemSource.open(..., "wb")`, read through `LocalFileSystemSource.open(..., "rb")`, and decoded through the same registry.
  - `LocalFileSystemSource.glob` over files written in the integration test returns sorted normalized file URIs suitable for later manifest construction.
  - Passive `ResourceRef` or `ArtifactRef` values are not given loading methods as part of the integration path.
- Targeted command: `make test-integration`.

### E2E Suite

- Deferred for this phase.
- Reason: Phase 3 has no config composition, pipeline parser, runner, stores, CLI path, or complete user-visible workflow. End-to-end pipeline behavior begins in Phase 9 after config, stores, planning, and execution exist.
- Expected command behavior: `make test-e2e` may report the suite as not present. If e2e tests already exist by the time Phase 3 is implemented, they should pass or any unrelated failure must be documented by PR preparation.

### Opt-In Suites

- Deferred for this phase.
- Reason: Phase 3 intentionally excludes remote sources, network access, optional storage dependencies, SLURM, subprocess execution, large artifacts, and slow tests.
- No opt-in network, remote-store, Windows-specific, or slow suite is required. If an opt-in check is introduced later, PR preparation should document why it is not relevant to this local standard-library phase.

## Risks

- URI normalization can accidentally make relative paths depend on process current working directory. Mitigation: keep `normalize_uri` caller-owned for relative paths and test root/base behavior explicitly.
- `file://` parsing can mishandle quoted characters or authorities. Mitigation: use standard-library URL parsing/quoting and test spaces plus `localhost`.
- JSON codec could blur serialization and I/O by accepting arbitrary objects. Mitigation: require `ensure_plain_data` and test dataclass/path/datetime/bytes/set rejection.
- Local source write support could be mistaken for artifact-store-safe persistence. Mitigation: document and test that it is simple open/truncate behavior only; Phase 7 owns atomic writes and checksums.
- Registry errors can degrade to plain `KeyError` or hidden duplicates. Mitigation: unit-test duplicate registration and unknown lookup messages.
- Adding contract and integration suites may expose pre-existing harness assumptions because those directories are currently absent. Mitigation: keep tests small and use existing Make targets named in `tests/README.md`.

## Validation Commands

Targeted development commands:

```sh
make test-package
make test-unit
make test-contract
make test-integration
uv run pytest tests/unit/loom/io
uv run pytest tests/contracts/test_codec_contract.py tests/contracts/test_data_source_contract.py
uv run pytest tests/integration/test_io_basics.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

`make validate-pr` is expected to run Ruff, Pyright, default Pytest, and build checks. `make test-summary` is expected to write suite-level evidence for the PR body. If network or cache permissions require `UV_CACHE_DIR=/tmp/uv-cache`, the PR preparation agent should use that environment setting and record it.

## Refinement And Review Budget Status

- Phase implementation refinement: unused.
- PR review: unused.

The plan quality gate budget for the canonical v0 plan is already fully used and passed with no remaining blockers. Do not start another plan-quality review cycle unless the manager explicitly instructs it.

## Handoff Notes For Plan Expansion Agent

- Review whether the draft default helper `create_default_codec_registry()` should remain in scope. It is included here because it returns a fresh explicit instance and matches `docs/features/io.md`; remove it only if the final expanded plan needs the smallest possible public surface.
- Preserve the boundary that `JSONCodec` accepts already-plain data and does not perform arbitrary object-to-plain conversion.
- Preserve the decision to defer `SourceRegistry` and load helpers unless you identify a blocking contradiction in the canonical Phase 3 source phase.
- Confirm expected public exports and test paths against the existing Make harness before marking the expanded plan final.
- Keep implementation refinement and PR review budget status visible and unchanged as unused.

## Completion Notes

- Draft plan committed by `loom_phase_planner`: pending.
- Final expanded plan committed by `loom_phase_plan_expander`: pending.
- Implementation summary: pending.
- Validation evidence: pending.
- PR: pending.
- Remaining blockers: none at draft-plan time.
