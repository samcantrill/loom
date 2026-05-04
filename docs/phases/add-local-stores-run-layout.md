# Phase 7 Execution Plan: Local Stores And Run Layout

## Metadata

- Status: PR open
- Branch: `codex/add-local-stores-run-layout`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-local-stores-run-layout`
- Phase execution plan path: `docs/phases/add-local-stores-run-layout.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0.md`
- Source phase: `Phase 7 - Local Stores And Run Layout`
- Stack predecessor: none
- Base branch: `develop` at `e9407f427314f88aec0324946f125529d4cd93ce`
- Target branch: `develop`
- PR: https://github.com/samcantrill/loom/pull/11
- Merge eligibility: root phase PR; reviewable and merge-eligible only while targeting `develop`.
- Successor dependency notes: no successor branch is recorded yet. Keep this phase branch until the PR is merged and any future successor has been rebased or retargeted away from it.
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no blocking findings remain in the canonical v0 plan.
- Plan quality gate loop budget: initial review used, automated plan refinement pass used, confirmation review used. Do not rerun or consume the plan-quality gate for this phase.
- Draft pass: completed by `loom_phase_planner` on 2026-05-04 local time.
- Refine pass: completed by `loom_phase_planner` on 2026-05-04 local time.
- PR body path: `docs/phases/add-local-stores-run-layout-pr-body.md`
- PR body draft pass: completed by `loom_pr_preparer` on 2026-05-04 local time.
- PR body refine pass: completed by `loom_pr_preparer` on 2026-05-04 local time.
- Setup limitations: manager verified the control checkout was clean and synced to `origin/develop` at `e9407f427314f88aec0324946f125529d4cd93ce` before assignment. The draft pass created the worktree from local `develop`; an initial sandboxed `git worktree add` could not create the branch ref and was rerun with approved filesystem access. No remote synchronization or validation commands were run in this draft pass.
- Blockers: none

## Objective

Implement durable local artifact and run state without planning or executing stages. This phase creates the store protocols, local filesystem store implementations, atomic write helpers, artifact indexes, and the inspectable v0 run directory layout that later planning and execution phases will consume.

The phase should make run state plain-file inspectable and stable enough for future same-run-directory resume tests, while keeping stage fingerprint calculation, resume decisions, runner lifecycle, CLI behavior, remote stores, and cross-run cache reuse out of scope.

## Full-Plan Context

Phases 1 through 6 are merged into `develop`. They provide import-safe package boundaries, primitives, serialization, generic local I/O and codecs, trusted config composition and recipe expansion, object instantiation helpers, static pipeline specs, graph validation, stage context, stage protocol, and in-memory status records.

Phase 7 is the persistence boundary between those pure/static layers and later runtime behavior:

- Phase 7 persists local run/artifact state, but does not compute plans or run stages.
- Phase 8 will compute plans, selectors, stage fingerprints, and conservative resume decisions using the store state created here.
- Phase 9 will execute stages, validate outputs, drive lifecycle transitions, and use the run/artifact stores to persist real runs.
- Phase 10 will harden error reporting, interrupted-run behavior, docs, and extension contract tests after the local runtime exists.

Future-phase work that must remain out of scope includes actual stage execution, runner lifecycle helpers, resume planning, downstream invalidation, stage fingerprint calculation, selector behavior, output validation by a runner, CLI commands, remote stores, global run catalogs, cross-run cache reuse, subprocess/SLURM execution, lock managers unless tests expose a concrete need, and domain-specific artifact helpers.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: Phases 1 through 6 are merged into latest `develop`; the manager explicitly directed Phase 7 to start from `develop`, not from any old Phase 5 or Phase 6 branch.
- Retarget/rebase plan after predecessor merge: no predecessor retarget is needed. If `develop` moves before PR preparation, the PR preparer should rebase or replay this branch onto updated `develop`, rerun validation, and record the stack maintenance.
- Branch cleanup constraints: this root branch can be deleted after merge only if no successor branch depends on it.

## Source Phase Summary

- Goal: implement durable local artifact/run state, atomic writes, and the inspectable local run directory layout without planning or executing stages.
- Required scope:
  - Add artifact and run store protocols.
  - Add local artifact and run stores.
  - Add atomic write helpers for JSON, text, bytes, replacement, directory creation, and unique temporary filenames.
  - Add run/artifact indexes using logical artifact keys of the form `stage.output`.
  - Add persistence helpers for run metadata, root status, plan, config snapshots, provenance documents, stage status, inputs, outputs, fingerprints, failures, logs, and artifact indexes.
  - Define the required local run layout under `run.json`, `status.json`, `plan.json`, `artifacts.json`, `config/`, `provenance/`, `stages/<stage>/`, and `artifacts/<stage>/`.
- Required checkpoints:
  - `ArtifactStore` exposes `save`, `load`, `register`, `exists`, and `validate`/checksum validation behavior.
  - `LocalArtifactStore` uses `CodecRegistry`, writes through temp paths and atomic moves where possible, computes stored-byte checksums, and returns typed `ArtifactRef`s.
  - `register` accepts already-written local files or file URIs, records checksums when requested, supports optional `codec_key`, and does not attempt generic serialization.
  - `RunStore` exposes run/stage directory resolution and read/write helpers for all Phase 7 state files.
  - Missing optional files return `None` where appropriate; missing required or corrupt state raises clear store errors.
- Acceptance criteria:
  - Artifacts save/load through JSON, text, and bytes codecs.
  - Already-written local files can be registered as artifacts with optional `codec_key`.
  - `ArtifactStore.load` fails clearly for codec-less artifacts unless an explicit codec is supplied.
  - Checksums are written and validated.
  - Run directory state is written atomically where possible.
  - Run status, plan, stage status, inputs, outputs, fingerprints, failures, artifact indexes, config snapshots, and provenance paths are read and written through the run store.
  - Local run directories contain the required v0 files and remain inspectable as plain JSON/YAML/text where applicable.
- Source references: `docs/implementation-plans/implementation-plan-v0.md` Phase 7; `docs/structure.md` sections "Stores and State", "Provenance and Resume", "Runtime Dependency Policy", "Test Layout", and "Review Checklist"; `docs/loom.md` sections 9, 10, and 11; `docs/features/run-store.md`, `docs/features/artifacts.md`, `docs/features/io.md`, `docs/features/serialization.md`, `docs/features/state.md`, `docs/features/provenance.md`, `docs/features/fingerprints.md`, `docs/features/reliability.md`, and `docs/features/testing.md`.

## Current Source And Harness Findings

- `src/loom/pipeline/stores/__init__.py` is currently an import-safe skeleton with no product behavior.
- `src/loom/artifacts.py` already provides frozen `ArtifactRef` values with `artifact_id`, `uri`, `artifact_type`, optional `codec_key`, schema version, checksum, fingerprint, producer stage, timestamp, metadata, and `to_dict`/`from_dict` helpers.
- `src/loom/io/codecs` already provides `Codec`, `CodecRegistry`, `create_default_codec_registry`, and JSON/text/bytes codecs with keys `json.v1`, `text.v1`, and `bytes.v1`.
- `src/loom/io/uris.py` already provides local path and `file://` conversion helpers; Phase 7 should reuse them for local refs instead of adding duplicate URI parsing.
- `src/loom/fingerprints.py` already provides digest validation, `hash_bytes`, and digest comparison helpers suitable for local file checksums.
- `src/loom/pipeline/status.py` already provides `RunStatusRecord` and `StageStatusRecord` serialization shapes. The run store should persist and read those records rather than inventing a parallel status model.
- `src/loom/pipeline/specs.py` validates stage/output names and already rejects output `path`; Phase 7 should allocate physical artifact paths in `LocalArtifactStore`, not in specs.
- `src/loom/serialization/json.py` already provides deterministic pretty JSON with trailing newlines. Atomic JSON helpers should call that serializer instead of adding another JSON formatting policy.
- `src/loom/serialization.PlainData` and `ensure_plain_data` already define the accepted persisted plain-data surface. Store JSON wrappers and metadata should normalize through those helpers.
- `src/loom/timestamps.py` already provides UTC timestamp formatting and parsing. Store-created wrapper timestamps should use `utc_timestamp()` with seconds precision.
- `StageContext` currently has paths and plain-data config/provenance only. Store-backed context helper fields are not part of this phase.
- Package import-boundary tests assert cheap root imports and that `loom.io` does not import config or pipeline. Store behavior belongs under `loom.pipeline.stores` and must not be exported from root `loom`.
- Test suites currently include package, unit, contract, and integration tests. There is no e2e suite directory yet.

## In-Scope Work

- Add store-specific errors under `loom.pipeline.stores`.
- Add an `ArtifactStore` structural protocol and `LocalArtifactStore` implementation.
- Add a `RunStore` structural protocol and `LocalRunStore` implementation.
- Add atomic filesystem helpers for deterministic JSON, UTF-8 text, bytes, file replacement, idempotent directory creation, and unique temp paths in the target directory.
- Add checksum helpers for regular local files saved or registered through the local artifact store.
- Add artifact index helpers that serialize and deserialize logical `stage.output` keys to `ArtifactRef` values.
- Add run directory path helpers for root files, config files, provenance files, stage files, log files, and stage artifact directories.
- Add read/write helpers for `run.json`, root `status.json`, `plan.json`, root `artifacts.json`, config snapshots, provenance documents, stage status, stage inputs, stage outputs, stage fingerprints, stage failures, and stage provenance.
- Export the Phase 7 store API from `loom.pipeline.stores` without adding root `loom` exports.
- Add focused package, unit, contract, and integration tests for local stores, atomic writes, indexes, manual artifact registration, codec-less artifact behavior, checksums, and required layout.

## Out-of-Scope Work

- No actual stage execution or executor behavior.
- No `PipelineRunner`, lifecycle orchestration, output validation, or stage target instantiation.
- No resume planning, selectors, downstream invalidation, or stage fingerprint calculation.
- No remote stores, remote source registries, content-addressed global stores, run catalogs, or cross-run cache reuse.
- No functional CLI behavior.
- No broad refactors outside the store boundary.
- No lock manager unless Phase 7 tests expose a concrete race that atomic writes cannot handle.
- No stage-bound context helpers such as `context.artifact_store.save(...)`, `context.output_path(...)`, or `context.register_artifact(...)`; those belong with runner/context wiring in Phase 9.

## Assumptions

- Store modules can use only the standard library plus existing project dependencies already introduced by earlier phases. No new runtime dependency is expected for Phase 7.
- Local run IDs, stage names, output names, and relative artifact paths must be path-safe even when earlier spec validation has already run; stores should protect filesystem boundaries independently.
- Local refs should be stored as `file://` URIs for future remote-store compatibility.
- `ArtifactStore.save()` owns serialization through codecs; `ArtifactStore.register()` owns metadata/checksum registration for content written by project code.
- `ArtifactStore.load()` requires either `ref.codec_key` or an explicit codec key. Existence and checksum validation still apply to codec-less artifacts.
- `LocalArtifactStore` should write regular files under the run's `artifacts/<stage>/` directory by default. External local registration, if supported in Phase 7, must be explicit and tested; otherwise it should fail clearly.
- Directory artifacts may be registered and checked for existence, but tree checksums and generic directory loading remain deferred.
- `RunStore` persists documents it is given. It does not compose configs, redact secrets, capture provenance, compute fingerprints, or decide stage/run lifecycle transitions.
- YAML config snapshots are persisted as caller-supplied UTF-8 text. `LocalRunStore` must not import `loom.config`, compose configs, redact secrets, or render YAML from Python objects.
- Atomic writes are best-effort for local filesystems: write temp file in the same directory, flush, fsync where practical, replace, and fsync the parent directory where practical.

## Decision-Complete Contract

This refined plan locks the Phase 7 behavioral contract and module ownership. The executor should implement these interfaces directly and stop for the manager if an acceptance criterion cannot be satisfied without changing an existing public value object.

### Module Boundaries And Exports

- Public package: `loom.pipeline.stores`. Do not add store exports to `loom.__init__` or `loom.pipeline.__init__` in Phase 7.
- Public modules to add:
  - `src/loom/pipeline/stores/errors.py`: store error hierarchy.
  - `src/loom/pipeline/stores/atomic.py`: atomic local filesystem write helpers.
  - `src/loom/pipeline/stores/indexes.py`: logical artifact index helpers.
  - `src/loom/pipeline/stores/artifact_store.py`: `ArtifactStore` protocol.
  - `src/loom/pipeline/stores/local_artifacts.py`: `LocalArtifactStore`.
  - `src/loom/pipeline/stores/run_store.py`: `RunStore` protocol.
  - `src/loom/pipeline/stores/local_runs.py`: `LocalRunStore`.
- Internal path/name validation helpers may live in `src/loom/pipeline/stores/_paths.py` if sharing is useful. Do not export them unless implementation tests prove a public helper is needed.
- `loom.pipeline.stores.__all__` must export only the Phase 7 public API:
  - protocols and implementations: `ArtifactStore`, `LocalArtifactStore`, `RunStore`, `LocalRunStore`;
  - errors: `StoreError`, `ArtifactStoreError`, `RunStoreError`, `UnsafeStorePathError`, `UnsupportedArtifactURIError`, `ArtifactNotFoundError`, `MissingArtifactCodecError`, `ArtifactTypeMismatchError`, `ArtifactChecksumMismatchError`, `ArtifactChecksumUnsupportedError`, `RunAlreadyExistsError`, `RunNotFoundError`, `MissingStoreDocumentError`, `CorruptStoreDocumentError`, `StageStateNotFoundError`, `AtomicWriteError`;
  - atomic helpers: `ensure_dir`, `unique_temp_path`, `atomic_write_bytes`, `atomic_write_text`, `atomic_write_json`, `replace_file`;
  - index helpers: `format_artifact_key`, `parse_artifact_key`, `artifact_index_to_dict`, `artifact_index_from_dict`, `merge_artifact_index`.
- `loom.pipeline.stores` may import `loom.artifacts`, `loom.fingerprints`, `loom.io.codecs`, `loom.io.uris`, `loom.pipeline.status`, `loom.serialization`, and `loom.timestamps`. It must not import `loom.config`, planner, executor, CLI, or user target-loading code.

### Store Error Hierarchy

Use this hierarchy, with errors including the relevant path, URI, artifact key, run ID, or stage name in their message:

```python
class StoreError(PipelineError): ...
class ArtifactStoreError(StoreError, ArtifactError): ...
class RunStoreError(StoreError): ...

class UnsafeStorePathError(StoreError): ...
class AtomicWriteError(StoreError): ...

class UnsupportedArtifactURIError(ArtifactStoreError): ...
class ArtifactNotFoundError(ArtifactStoreError): ...
class MissingArtifactCodecError(ArtifactStoreError): ...
class ArtifactTypeMismatchError(ArtifactStoreError): ...
class ArtifactChecksumMismatchError(ArtifactStoreError): ...
class ArtifactChecksumUnsupportedError(ArtifactStoreError): ...

class RunAlreadyExistsError(RunStoreError): ...
class RunNotFoundError(RunStoreError): ...
class MissingStoreDocumentError(RunStoreError): ...
class CorruptStoreDocumentError(RunStoreError): ...
class StageStateNotFoundError(RunStoreError): ...
```

Wrap lower-level JSON decode errors, `ArtifactRef.from_dict()` errors, `RunStatusRecord.from_dict()` errors, `StageStatusRecord.from_dict()` errors, codec lookup/decode errors, and invalid wrapper shapes in store errors at the boundary. Do not let raw `json.JSONDecodeError`, `StatusSerializationError`, `ArtifactValidationError`, or `UnsupportedURIError` escape from public store methods.

### Protocol Signatures

Add `@runtime_checkable` structural protocols. Protocols should be method-only and should not require inheritance by downstream stores.

```python
class ArtifactStore(Protocol):
    def save(
        self,
        obj: object,
        *,
        run_id: str,
        stage_name: str,
        name: str,
        artifact_type: str,
        codec_key: str,
        schema_version: int = 1,
        metadata: Mapping[str, PlainData] | None = None,
        fingerprint: str | None = None,
    ) -> ArtifactRef: ...

    def register(
        self,
        uri: str | Path,
        *,
        run_id: str,
        stage_name: str,
        name: str,
        artifact_type: str,
        codec_key: str | None = None,
        schema_version: int = 1,
        metadata: Mapping[str, PlainData] | None = None,
        fingerprint: str | None = None,
        checksum: str | None = None,
        allow_external: bool = False,
    ) -> ArtifactRef: ...

    def load(
        self,
        ref: ArtifactRef,
        *,
        expected_type: str | None = None,
        codec_key: str | None = None,
    ) -> object: ...

    def exists(self, ref: ArtifactRef) -> bool: ...

    def verify_checksum(self, ref: ArtifactRef) -> bool: ...

    def validate(
        self,
        ref: ArtifactRef,
        *,
        expected_type: str | None = None,
    ) -> None: ...
```

```python
class RunStore(Protocol):
    def create_run(self, run_id: str, *, metadata: Mapping[str, PlainData] | None = None) -> Path: ...
    def open_run(self, run_id: str) -> Path: ...
    def get_run_dir(self, run_id: str) -> Path: ...
    def get_stage_dir(self, run_id: str, stage_name: str) -> Path: ...
    def get_artifact_root(self, run_id: str) -> Path: ...
    def get_stage_artifact_dir(self, run_id: str, stage_name: str) -> Path: ...
    def get_config_path(self, run_id: str, name: str) -> Path: ...
    def get_provenance_path(self, run_id: str, name: str) -> Path: ...
    def get_stage_log_path(self, run_id: str, stage_name: str, stream: str) -> Path: ...

    def read_run_metadata(self, run_id: str) -> dict[str, PlainData]: ...
    def write_run_metadata(self, run_id: str, metadata: Mapping[str, PlainData]) -> None: ...

    def read_run_status(self, run_id: str) -> RunStatusRecord | None: ...
    def write_run_status(self, run_id: str, status: RunStatusRecord) -> None: ...

    def read_plan(self, run_id: str) -> dict[str, PlainData] | None: ...
    def write_plan(self, run_id: str, plan: Mapping[str, PlainData]) -> None: ...

    def read_artifact_index(self, run_id: str) -> dict[str, ArtifactRef]: ...
    def write_artifact_index(self, run_id: str, index: Mapping[str, ArtifactRef]) -> None: ...

    def read_config_snapshot(self, run_id: str, name: str) -> str | None: ...
    def write_config_snapshot(self, run_id: str, name: str, content: str) -> None: ...
    def read_recipe_manifest(self, run_id: str) -> tuple[dict[str, PlainData], ...] | None: ...
    def write_recipe_manifest(self, run_id: str, records: Sequence[Mapping[str, PlainData]]) -> None: ...

    def read_provenance_document(self, run_id: str, name: str) -> dict[str, PlainData] | None: ...
    def write_provenance_document(self, run_id: str, name: str, document: Mapping[str, PlainData]) -> None: ...

    def read_stage_status(self, run_id: str, stage_name: str) -> StageStatusRecord | None: ...
    def write_stage_status(self, run_id: str, stage_name: str, status: StageStatusRecord) -> None: ...
    def read_stage_inputs(self, run_id: str, stage_name: str) -> dict[str, ArtifactRef] | None: ...
    def write_stage_inputs(self, run_id: str, stage_name: str, inputs: Mapping[str, ArtifactRef], *, attempt: int) -> None: ...
    def read_stage_outputs(self, run_id: str, stage_name: str) -> dict[str, ArtifactRef] | None: ...
    def write_stage_outputs(self, run_id: str, stage_name: str, outputs: Mapping[str, ArtifactRef], *, attempt: int) -> None: ...
    def read_stage_fingerprint(self, run_id: str, stage_name: str) -> dict[str, PlainData] | None: ...
    def write_stage_fingerprint(self, run_id: str, stage_name: str, fingerprint: Mapping[str, PlainData], *, attempt: int) -> None: ...
    def read_stage_failure(self, run_id: str, stage_name: str) -> dict[str, PlainData] | None: ...
    def write_stage_failure(self, run_id: str, stage_name: str, failure: Mapping[str, PlainData], *, attempt: int) -> None: ...
    def read_stage_provenance(self, run_id: str, stage_name: str) -> dict[str, PlainData] | None: ...
    def write_stage_provenance(self, run_id: str, stage_name: str, provenance: Mapping[str, PlainData], *, attempt: int) -> None: ...
    def read_stage_log(self, run_id: str, stage_name: str, stream: str) -> str | None: ...
    def write_stage_log(self, run_id: str, stage_name: str, stream: str, content: str) -> None: ...
```

### Local Implementations

`LocalRunStore`:

```python
class LocalRunStore:
    def __init__(self, root: str | Path) -> None: ...
```

- `root` is the directory containing run directories. `get_run_dir(run_id)` returns `root / run_id`.
- `create_run()` creates the run directory and reserved subdirectories `config/`, `provenance/`, `stages/`, and `artifacts/`, then writes `run.json` using `write_run_metadata()`. It raises `RunAlreadyExistsError` if the run directory already exists.
- `open_run()` returns an existing run directory and raises `RunNotFoundError` if absent. It validates `run.json` if present and raises `CorruptStoreDocumentError` for malformed content.
- `get_artifact_root(run_id)` returns `get_run_dir(run_id) / "artifacts"`; `get_stage_artifact_dir(run_id, stage_name)` returns `get_artifact_root(run_id) / stage_name`.
- All path helpers validate names before building paths and call `resolve(strict=False)` containment checks for paths under the run root.

`LocalArtifactStore`:

```python
class LocalArtifactStore:
    def __init__(
        self,
        root: str | Path,
        *,
        codec_registry: CodecRegistry | None = None,
    ) -> None: ...
```

- `root` is the artifact root for one run, normally `LocalRunStore.get_run_dir(run_id) / "artifacts"`.
- `save()` writes under `root / stage_name` and does not include `run_id` in the filesystem path. `run_id` remains part of the protocol and may be recorded in metadata by future store implementations.
- `LocalArtifactStore` uses `create_default_codec_registry()` when no registry is supplied.
- It may expose implementation-specific `get_stage_dir(run_id, stage_name) -> Path`, `allocate_path(run_id, stage_name, name, codec_key) -> Path`, and `local_path(ref) -> Path` helpers, but these are not exported from `loom.pipeline.stores.__all__` unless they are methods on the class.

### Path Allocation And Safe Names

- Run IDs, stage names, output names, artifact names, config snapshot names, provenance document names, and log stream names must be validated before filesystem access.
- Safe path components are non-empty strings, not `.` or `..`, with no `/`, `\`, NUL, control characters, or whitespace. Stage and output names also cannot contain `.` because logical artifact keys use `stage.output`.
- Artifact logical keys are exactly `stage.output`. `format_artifact_key()` validates both parts; `parse_artifact_key()` rejects missing parts, extra dots, and unsafe parts.
- `LocalArtifactStore.save()` allocates `root/<stage>/<name><suffix>` where suffix is `.json` for `json.v1`, `.txt` for `text.v1`, `.bin` for `bytes.v1`, and no suffix for other registered codecs. This phase does not implement output path templates or accept arbitrary save paths.
- Saved artifacts use stable artifact IDs of `stage_name/name`, `file://` URIs for absolute paths, `producer_stage=stage_name`, `schema_version` from the argument, `created_at=utc_timestamp()`, and metadata normalized through `ensure_plain_data`.
- Stable output paths may be atomically replaced by later writes in the same run. Attempt history remains deferred.
- `register()` accepts only local filesystem paths or local `file://` URIs. Remote URI schemes raise `UnsupportedArtifactURIError`.
- By default, `register()` requires the resolved path to be inside `root/<stage_name>/`. A per-call `allow_external=True` permits an absolute local file outside the run artifact root and records the absolute `file://` URI; it does not copy or rewrite the file. External local registration must be explicitly tested.
- `register()` must reject missing paths, non-regular-file/non-directory paths, unsafe paths, or paths that escape the stage artifact directory when `allow_external=False`.

### Checksum And Load Behavior

- `save()` computes `sha256` over the exact stored bytes after encoding and writes the digest to `ArtifactRef.checksum`.
- `register()` computes `sha256` for regular local files when `checksum` is not supplied. When `checksum` is supplied for a regular file, it validates the digest syntax and compares the file content before returning the ref. Mismatch raises `ArtifactChecksumMismatchError`.
- Directory artifacts can be registered and checked for existence, but Phase 7 does not compute or accept directory checksums. A supplied checksum for a directory raises `ArtifactChecksumUnsupportedError`.
- `verify_checksum(ref)` returns `True` only when `ref.checksum` is present and the local regular file matches it. It returns `False` when no checksum is present. It raises `ArtifactChecksumUnsupportedError` for directories with checksums and `ArtifactChecksumMismatchError` for mismatches.
- `exists(ref)` supports local `file://` refs only. Unsupported URI schemes raise `UnsupportedArtifactURIError`.
- `validate(ref, expected_type=None)` checks artifact type when supplied, URI support, existence, and checksum when present. It returns `None` on success and raises a store error on failure.
- `load(ref, expected_type=None, codec_key=None)` calls `validate()` first, resolves `codec_key or ref.codec_key`, and raises `MissingArtifactCodecError` if neither is available. It then reads bytes and decodes through the registry. Codec decode/lookup failures are wrapped in `ArtifactStoreError` with the codec key and artifact URI.

### Atomic Helpers

Implement these public helpers in `atomic.py`:

```python
def ensure_dir(path: str | Path) -> Path: ...
def unique_temp_path(path: str | Path) -> Path: ...
def atomic_write_bytes(path: str | Path, data: bytes) -> None: ...
def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> None: ...
def atomic_write_json(path: str | Path, value: object) -> None: ...
def replace_file(source: str | Path, target: str | Path) -> None: ...
```

`atomic_write_json()` must use `loom.serialization.json.json_dumps_pretty()` so state files are deterministic and newline-terminated. All atomic writers write a temp file in the target directory, flush and fsync where practical, replace with `os.replace()`, fsync the parent directory where practical, and remove the temp file on failure. Filesystem failures are wrapped as `AtomicWriteError`.

### Artifact Index Helpers

Use these exact signatures for index helpers:

```python
def format_artifact_key(stage_name: str, output_name: str) -> str: ...
def parse_artifact_key(key: str) -> tuple[str, str]: ...
def artifact_index_to_dict(index: Mapping[str, ArtifactRef]) -> dict[str, PlainData]: ...
def artifact_index_from_dict(data: object) -> dict[str, ArtifactRef]: ...
def merge_artifact_index(
    index: Mapping[str, ArtifactRef],
    updates: Mapping[str, ArtifactRef],
    *,
    replace: bool = False,
) -> dict[str, ArtifactRef]: ...
```

`artifact_index_to_dict()` returns a plain-data mapping from logical keys to `ArtifactRef.to_dict()` payloads. `artifact_index_from_dict()` returns `dict[str, ArtifactRef]` and wraps invalid payloads in store errors. `merge_artifact_index()` returns a new dict, rejects duplicate logical keys with different refs by default, and permits replacement only when `replace=True`.

### Persisted Document Shapes

Do not add new public dataclasses for Phase 7 wrappers. Existing `ArtifactRef`, `RunStatusRecord`, `StageStatusRecord`, and plain-data mappings are enough. Wrapper construction/parsing should be internal helper functions in `local_runs.py` or a private helper module. `RunStore` read methods return the inner payloads named in their method, not the full wrapper, except status reads return the existing status record classes and artifact index reads return `dict[str, ArtifactRef]`.

All machine-written JSON uses `schema_version: 1`, deterministic key order, and a trailing newline. Present-but-corrupt JSON, wrong wrapper kind, invalid serialized records, or non-plain-data payloads raise `CorruptStoreDocumentError` with the path. Missing optional documents return `None`; `read_artifact_index()` returns an empty dict when `artifacts.json` is absent. `read_run_metadata()` is the required root read and raises `MissingStoreDocumentError` when `run.json` is absent.

Exact wrappers:

```text
run.json:
{
  "schema_version": 1,
  "run_id": "<run_id>",
  "created_at": "<UTC timestamp>",
  "run_dir": "file:///absolute/run/dir",
  "metadata": {}
}
```

`status.json` is exactly `RunStatusRecord.to_dict()`. `stages/<stage>/status.json` is exactly `StageStatusRecord.to_dict()`.

```text
plan.json:
{
  "schema_version": 1,
  "run_id": "<run_id>",
  "updated_at": "<UTC timestamp>",
  "plan": {}
}

artifacts.json:
{
  "schema_version": 1,
  "run_id": "<run_id>",
  "updated_at": "<UTC timestamp>",
  "artifacts": {
    "<stage>.<output>": { "...ArtifactRef.to_dict()": "..." }
  }
}

stages/<stage>/inputs.json:
{
  "schema_version": 1,
  "run_id": "<run_id>",
  "stage_name": "<stage>",
  "attempt": 1,
  "created_at": "<UTC timestamp>",
  "inputs": {
    "<input_name>": { "...ArtifactRef.to_dict()": "..." }
  }
}

stages/<stage>/outputs.json:
{
  "schema_version": 1,
  "run_id": "<run_id>",
  "stage_name": "<stage>",
  "attempt": 1,
  "created_at": "<UTC timestamp>",
  "outputs": {
    "<output_name>": { "...ArtifactRef.to_dict()": "..." }
  }
}

stages/<stage>/fingerprint.json:
{
  "schema_version": 1,
  "run_id": "<run_id>",
  "stage_name": "<stage>",
  "attempt": 1,
  "created_at": "<UTC timestamp>",
  "fingerprint": {}
}

stages/<stage>/failure.json:
{
  "schema_version": 1,
  "run_id": "<run_id>",
  "stage_name": "<stage>",
  "attempt": 1,
  "failed_at": "<UTC timestamp>",
  "failure": {}
}

stages/<stage>/provenance.json:
{
  "schema_version": 1,
  "run_id": "<run_id>",
  "stage_name": "<stage>",
  "attempt": 1,
  "created_at": "<UTC timestamp>",
  "provenance": {}
}

provenance/<name>.json:
{
  "schema_version": 1,
  "run_id": "<run_id>",
  "kind": "<environment|git|command|dependencies>",
  "created_at": "<UTC timestamp>",
  "provenance": {}
}

config/recipe_manifest.json:
{
  "schema_version": 1,
  "run_id": "<run_id>",
  "created_at": "<UTC timestamp>",
  "recipe_manifest": []
}
```

Config YAML snapshot files are deliberately unwrapped caller-supplied text:

```text
config/raw.yaml
config/overlays.yaml
config/cli_overrides.yaml
config/resolved.yaml
config/resolved.redacted.yaml
```

Stage log files are deliberately unwrapped caller-supplied UTF-8 text:

```text
stages/<stage>/logs/stdout.log
stages/<stage>/logs/stderr.log
```

Valid config snapshot names are `raw`, `overlays`, `cli_overrides`, `resolved`, and `resolved_redacted`, mapped to the filenames above. Valid root provenance document names are `environment`, `git`, `command`, and `dependencies`. Valid log streams are `stdout` and `stderr`.

Required local run layout:

```text
run.json
status.json
plan.json
artifacts.json
config/raw.yaml
config/overlays.yaml
config/cli_overrides.yaml
config/resolved.yaml
config/resolved.redacted.yaml
config/recipe_manifest.json
provenance/environment.json
provenance/git.json
provenance/command.json
provenance/dependencies.json
stages/<stage>/status.json
stages/<stage>/inputs.json
stages/<stage>/outputs.json
stages/<stage>/fingerprint.json
stages/<stage>/failure.json
stages/<stage>/provenance.json
stages/<stage>/logs/stdout.log
stages/<stage>/logs/stderr.log
artifacts/<stage>/
```

Error behavior:

- Unsafe run IDs, stage names, output names, artifact paths, config snapshot names, provenance document names, log stream names, or temp paths must fail before filesystem writes.
- Unsupported remote URIs must fail clearly in local stores.
- Missing codec keys on generic load must fail as artifact/store errors that name the artifact and state how to supply a codec.
- Checksum mismatch must fail validation and should include the artifact URI and expected/actual digest.
- Missing optional documents return `None` or an empty artifact index as specified above. Missing `run.json` raises `MissingStoreDocumentError`. Corrupt present documents always raise `CorruptStoreDocumentError`.
- Atomic helper failures should clean up the temp path where possible and raise a store-specific atomic-write error.

## Design Impact

- Maintainability: centralizing local persistence in store modules keeps runner, planner, CLI, and value objects from duplicating path and serialization policy.
- Extensibility: structural protocols plus local implementations leave room for remote artifact stores, run catalogs, and alternate persistence backends after v0 without changing artifact refs or status records.
- Domain neutrality: stores persist generic artifacts, statuses, configs, provenance, and plain metadata only; no domain-specific artifact types, schemas, datasets, models, or reports enter `loom`.
- Source-tree boundaries: serialization remains separate from filesystem I/O; I/O remains the codec/source layer; stores own persistent state; planning and execution remain deferred.

## Future Compatibility

- Remote stores should be able to implement the same protocols later while preserving `ArtifactRef` URI semantics.
- Same-run-directory resume in Phase 8 should consume the run store's status, plan, fingerprint, output, and artifact-index helpers rather than scanning ad hoc paths.
- Local execution in Phase 9 should use store path helpers for contexts, logs, config/provenance persistence, stage outputs, failures, and artifact directories.
- CLI/status/artifact inspection in later phases should be possible by reading plain JSON/YAML/text files without importing user project code.
- Optional lock files and run catalogs remain possible because the layout reserves stable root files and avoids global mutable state.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implement runner lifecycle in Phase 7 | Stage execution and lifecycle orchestration belong to Phase 9; Phase 7 should be reviewable as persistence only. |
| Implement resume planning in the run store | Resume policy belongs to Phase 8 planning and must consider fingerprints, selectors, status, and artifact validation together. |
| Add a lock manager immediately | The v0 plan accepts atomic writes first; locks are revisited only if tests expose a concrete race. |
| Let stages or specs choose physical output paths | Output path templates are deferred; Phase 7 should allocate safe local artifact paths in `LocalArtifactStore`. |
| Store only opaque blobs or binary state | The v0 run layout must remain human-inspectable as plain JSON/YAML/text. |
| Add remote store support now | Remote stores are explicitly deferred and would widen review scope. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No lock manager in v0 Phase 7 | Atomic writes and conservative later resume validation keep the first local store implementation small. | Atomic-write, interrupted-run, or concurrent-run tests expose a concrete race or partial-state ambiguity. |
| No tree checksum for directory artifacts | Regular-file checksums satisfy the required v0 save/register/load path; directory checksum policy needs a separate design. | Directory artifacts become part of resume correctness or downstream users need integrity verification for directory outputs. |
| No cross-run artifact catalog or content-addressed cache | The v0 plan requires same-run-directory resume only and local inspectability first. | Phase 8/9 local resume is stable and a later plan adds global discovery or cache reuse. |

## Reviewability

- Expected PR size and shape: one bounded store-layer PR with new modules under `src/loom/pipeline/stores/`, export updates in `src/loom/pipeline/stores/__init__.py`, and focused tests under package/unit/contract/integration suites.
- Files and areas to inspect:
  - `src/loom/pipeline/stores/errors.py`
  - `src/loom/pipeline/stores/atomic.py`
  - `src/loom/pipeline/stores/artifact_store.py`
  - `src/loom/pipeline/stores/local_artifacts.py`
  - `src/loom/pipeline/stores/run_store.py`
  - `src/loom/pipeline/stores/local_runs.py`
  - `src/loom/pipeline/stores/indexes.py`
  - optional internal `src/loom/pipeline/stores/_paths.py`
  - `src/loom/pipeline/stores/__init__.py`
  - package import-boundary tests
  - unit tests for stores, atomic helpers, and indexes
  - contract tests for store protocols
  - integration tests for local layout and codec-backed artifact operations
- Scope-control checks:
  - no `PipelineRunner`, planner, selector, executor, or CLI behavior
  - no top-level `loom.__init__` exports
  - no remote store implementation
  - no new heavyweight runtime dependency
  - no stage execution or target construction

## Implementation Steps

1. Add the store error hierarchy, optional internal path validators, and `loom.pipeline.stores.__all__` scaffolding without exporting stores from root `loom` or `loom.pipeline`.
2. Add atomic filesystem helpers and unit tests for deterministic JSON/text/bytes writes, replacement, idempotent directory creation, temp path uniqueness, and cleanup on simulated write failure.
3. Add artifact index helpers and unit tests for `stage.output` formatting/parsing, invalid key rejection, `ArtifactRef` round-trips, deterministic serialization, and duplicate-key rejection.
4. Add `ArtifactStore` and `RunStore` protocols with package/contract tests proving runtime structural compatibility.
5. Add `LocalArtifactStore` path allocation, codec-backed save/load, local registration, existence, checksum, validation, and URI normalization behavior.
6. Add `LocalRunStore` create/open behavior and central path helpers for root, config, provenance, stage, log, and artifact directories.
7. Add `LocalRunStore` JSON/YAML/text read/write helpers for run metadata, run status, plan, artifact index, config snapshots, recipe manifest, root provenance, stage status, stage inputs, stage outputs, stage fingerprints, stage failures, stage provenance, and logs.
8. Add integration tests that create a synthetic run directory, instantiate `LocalArtifactStore` from `LocalRunStore.get_artifact_root(run_id)`, save/load/register artifacts, write/read every required document kind, and assert the exact v0 layout without planning or executing stages.
9. Run targeted package, unit, contract, and integration checks during implementation, then leave final `make validate-pr` and `make test-summary` for PR preparation as required.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_store_api.py` and existing import-boundary tests if public exports change.
- Required assertions or deferral reason: `loom.pipeline.stores.__all__` exactly matches the export list in this plan; direct `import loom.pipeline.stores` succeeds; root `loom` still does not import or export stores; `loom.pipeline.__all__` remains unchanged; importing `loom.io` still does not import `loom.pipeline`; importing `loom.pipeline.stores` does not import `loom.config`, `loom.cli`, planner, executor, or user-target modules.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_atomic.py`, `tests/unit/loom/pipeline/stores/test_indexes.py`, `tests/unit/loom/pipeline/stores/test_local_artifacts.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, and `tests/unit/loom/pipeline/stores/test_store_errors.py`.
- Required assertions or deferral reason: atomic writes are deterministic and clean up temp files; unsafe path components and invalid logical artifact keys fail before writes; default codec suffix allocation is `name.json`, `name.txt`, `name.bin`, or `name`; saved artifacts compute `sha256` over stored bytes; JSON/text/bytes save/load round-trip through `CodecRegistry`; codec-less loads fail with `MissingArtifactCodecError` unless an explicit codec is supplied; external registration fails by default and succeeds only with `allow_external=True`; directory registration works without checksums and rejects supplied checksums; checksum mismatches raise `ArtifactChecksumMismatchError`; unsupported URI schemes raise `UnsupportedArtifactURIError`; run store read/write helpers produce the exact wrappers in this plan; missing optional documents return `None`, missing `artifacts.json` returns `{}`, missing `run.json` raises `MissingStoreDocumentError`, and corrupt present files raise `CorruptStoreDocumentError`.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py` or split store contract files if clearer.
- Required assertions or deferral reason: downstream-style fake stores satisfy `ArtifactStore` and `RunStore` structurally without inheritance; `LocalArtifactStore` and `LocalRunStore` satisfy their protocols under `isinstance(..., Protocol)` runtime checks; the protocol tests cover method signatures but avoid remote stores, planning, execution, CLI behavior, and domain-specific artifacts.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_stores.py` or `tests/integration/test_local_stores.py`.
- Required assertions or deferral reason: local run directory creation produces `run.json`, `config/`, `provenance/`, `stages/`, and `artifacts/`; path helpers resolve inside the run root; artifact store and run store work together under one temp run directory; JSON/text/bytes artifacts save/load; an already-written file under `artifacts/<stage>/` can be registered; root status, plan, artifact index, stage status, inputs, outputs, fingerprints, failures, config snapshots, root provenance documents, stage provenance, and logs can be written and read through store APIs; artifact refs in `outputs.json` and root `artifacts.json` round-trip through `ArtifactRef.from_dict()`; no planner, selector, fingerprint calculation, runner lifecycle, stage execution, target construction, CLI, or remote store behavior is involved.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 7 has no runner, CLI, or end-to-end pipeline execution surface. E2E coverage starts when Phase 9 wires local execution and public runtime entry points.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected.
- Required assertions or deferral reason: no remote, network, SLURM, subprocess, slow, or optional-dependency behavior is in scope for Phase 7.

## Risks

- Store protocols can become too broad if they absorb planning or runner lifecycle decisions. Keep them to persistence and path helpers.
- Atomic writes differ subtly by filesystem. Tests should assert observable local behavior and cleanup rather than platform-specific internals.
- Allowing external local registration too freely can break reproducibility. The default should be conservative and explicit.
- Persisted JSON wrapper shapes can drift from existing `ArtifactRef`, `RunStatusRecord`, and `StageStatusRecord` serialization. Tests should round-trip through existing value objects.
- Config snapshot helpers could accidentally make stores own config composition or redaction. Stores should only persist supplied content.
- Adding exports from `loom.pipeline` or root `loom` could break import-boundary expectations. Exports should stay in `loom.pipeline.stores`.

## Validation Commands

Targeted development commands:

```sh
make test-package
make test-unit
make test-contract
make test-integration
uv run pytest tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - errors, export list, optional internal path validators, and package tests
  - atomic helpers plus `tests/unit/loom/pipeline/stores/test_atomic.py`
  - artifact index helpers plus `tests/unit/loom/pipeline/stores/test_indexes.py`
  - protocols plus package/contract tests
  - `LocalArtifactStore` plus `tests/unit/loom/pipeline/stores/test_local_artifacts.py`
  - `LocalRunStore` path and document helpers plus `tests/unit/loom/pipeline/stores/test_local_runs.py`
  - combined integration coverage plus `tests/integration/pipeline/test_local_stores.py`
- Tests to run with each slice: run the nearest unit test file for the edited module; after public exports and protocols land, run `uv run pytest tests/package/test_pipeline_store_api.py tests/contracts/test_store_contract.py`; after local implementations land, run the focused integration test. Broad `make validate-pr` and `make test-summary` remain PR-preparer obligations.
- Decisions the executor must not revisit:
  - no stage execution, planning, selectors, resume, CLI, remote stores, or lock manager by default
  - public exports stay under `loom.pipeline.stores` only
  - no new public wrapper dataclasses in Phase 7
  - physical local artifact paths are owned by `LocalArtifactStore`
  - run layout path formatting is centralized in `LocalRunStore`
  - logical artifact keys are `stage.output`
  - `LocalArtifactStore.save()` uses the suffix allocation specified here and does not accept arbitrary save paths
  - `register()` is local-only and external local registration is explicit per call
  - codec-less artifacts cannot be generically loaded without an explicit codec
  - YAML config snapshots and logs are caller-supplied text, not parsed or composed by stores
- Conditions that require stopping for the manager:
  - exact store protocol cannot cover the Phase 7 acceptance criteria without changing earlier public value objects
  - atomic-write tests prove a lock manager is required to satisfy the phase
  - existing Phase 6 status/spec contracts conflict with required persisted layout
  - final targeted suites expose failures that would require implementing Phase 8 or Phase 9 behavior

## Refinement And Review Budget Status

- Phase implementation refinement: used
- PR review: used before this post-review blocker fix; the normal review loop
  is not being rerun by this pass.
- User-authorized post-review blocker fix: used on 2026-05-04 local time for
  PR #11 review blockers; this was explicitly requested by the user after the
  normal Phase 7 refinement/review budgets were consumed and is not an
  unrequested extra automated loop.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; recorded in the `plan: add phase execution plan` commit for this artifact.
- Final phase execution plan: completed by `loom_phase_planner` in the refine pass; exact exports, method signatures, path/checksum behavior, document wrappers, and suite-level tests are recorded above.
- Implementation summary:
  - Added local store errors, atomic helpers, artifact index helpers, protocol definitions, local artifact store, and local run store under `src/loom/pipeline/stores/`.
  - Exported Phase 7 store API in `src/loom/pipeline/stores/__init__.py` only, including exact `__all__` list and error, helper, protocol, and index exports.
  - Implemented local artifact save/register/load/validate/checksum behavior with local-only URI enforcement and register stage-root path validation.
  - Implemented local run persistence for run metadata, status, plan, artifacts index, config snapshots, recipe manifest, provenance documents, stage inputs/outputs/failure/fingerprint/provenance/logs.
  - Added/updated Phase 7-focused unit, contract, package, and integration tests under `tests/unit/loom/pipeline/stores`, `tests/contracts/test_store_contract.py`, and `tests/integration/pipeline/test_local_stores.py`.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=/home/samcantrill/work/loom-worktrees/add-local-stores-run-layout/src uv run pytest tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py`
  - `UV_CACHE_DIR=/tmp/uv-cache make test-package`
  - `UV_CACHE_DIR=/tmp/uv-cache make test-unit`
  - `UV_CACHE_DIR=/tmp/uv-cache make test-contract`
  - `UV_CACHE_DIR=/tmp/uv-cache make test-integration`
  - All passing.
- Refinement summary:
  - Phase implementation refinement budget consumed by `loom_phase_refiner` on 2026-05-04 local time.
  - Validation output reviewed: executor's passing Phase 7 targeted package/unit/contract/integration checks and manager-reported `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` failure at `uv run ruff check .`.
  - Blocking issues caused by this phase:
    - Ruff F401 failures from unused `RunStore`, `ArtifactRef`, and `LocalArtifactStore` imports.
    - Pyright failures in local store metadata normalization, JSON payload narrowing, and one unit-test plan payload annotation surfaced after Ruff was fixed.
    - Directory-artifact checksum coverage was unreachable because it was nested under an earlier expected checksum failure.
    - Local artifact directory loads and corrupt run-store artifact/stage wrapper shapes could leak unclear or cross-store errors instead of Phase 7 store-boundary errors.
  - Issues confirmed out of scope: no planning, resume, selectors, fingerprint calculation, runner lifecycle, CLI behavior, remote stores, lock manager, or cross-run cache behavior was changed.
  - Fixes made:
    - Removed unused imports reported by Ruff.
    - Added typed metadata normalization in `LocalArtifactStore`, clear `ArtifactTypeMismatchError` for non-file artifact loads, and restored directory checksum/load regression coverage.
    - Narrowed `LocalRunStore` JSON document reads for Pyright and corrupt-document behavior, wrapped malformed artifact index refs as `CorruptStoreDocumentError`, and aligned public run-store protocol metadata typing with the finalized phase plan.
    - Added regression tests for non-mapping stage document payloads and malformed artifact-index refs.
  - Tests or validation re-run:
    - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` — passed.
    - `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=/home/samcantrill/work/loom-worktrees/add-local-stores-run-layout/src uv run pytest tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py` — passed, 38 passed.
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pyright` — passed, 0 errors.
    - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` — passed; Ruff passed, Pyright passed, default test suite passed with 302 passed, and `uv build` produced source and wheel distributions.
  - Remaining blockers: none known after this refinement pass.
  - PR preparation handoff: completion notes and budget status updated here; `make test-summary` remains the PR-preparer suite evidence command.
- PR preparation:
  - Draft pass completed by `loom_pr_preparer` on 2026-05-04 local time.
  - Refine pass completed by `loom_pr_preparer` on 2026-05-04 local time.
  - PR body path: `docs/phases/add-local-stores-run-layout-pr-body.md`.
  - PR facts recorded for refine/open pass: base/target `develop`, head `codex/add-local-stores-run-layout`, stack predecessor none.
  - Merge eligibility: root phase PR; reviewable and merge-eligible only while targeting `develop`.
  - PR body refine verified the draft against the phase execution plan, actual diff, acceptance criteria, scope boundaries, assumptions, risks, and suite evidence.
  - Future-phase scope check: no Phase 8 planning/resume/selector behavior, Phase 9 runner/executor behavior, or Phase 10 hardening/documentation behavior was implemented early.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed in the PR body refine pass; Ruff passed, Pyright passed, default pytest passed with 302 passed, and `uv build` produced source and wheel distributions.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed in the PR body refine pass and wrote `build/test-summary.md`: package passed, unit passed, contract passed, integration passed, e2e not present.
  - GitHub authentication verified outside the sandbox with `gh auth status`; `origin/develop` resolved to `e9407f427314f88aec0324946f125529d4cd93ce`.
  - Branch pushed to `origin/codex/add-local-stores-run-layout`.
  - PR opened with `gh pr create --base develop --head codex/add-local-stores-run-layout --body-file docs/phases/add-local-stores-run-layout-pr-body.md --title "Phase 7: Local Stores And Run Layout"`.
  - PR URL: https://github.com/samcantrill/loom/pull/11.
  - PR verification JSON from `gh pr view 11 --json baseRefName,headRefName,state,url`: `{"baseRefName":"develop","headRefName":"codex/add-local-stores-run-layout","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/11"}`.
- Stack maintenance: none required at refine time; root phase targets `develop`.
- User-authorized post-review blocker fix:
  - Authorization: user explicitly requested this post-review blocker fix for
    PR #11 after the normal Phase 7 implementation refinement and PR body
    passes were consumed.
  - Fixes made:
    - Hardened `LocalRunStore` wrapper reads so present malformed `run.json`,
      `plan.json`, `artifacts.json`, recipe manifest, provenance documents,
      and stage attempt documents validate required fields, exact field set,
      field types, UTC timestamp fields, and mapping/list payload shape before
      returning caller-visible values.
    - Wrapped unsafe root artifact-index keys, unsafe stage artifact-index
      keys, and malformed `ArtifactRef` payloads from persisted indexes as
      `CorruptStoreDocumentError` messages naming the source JSON document.
    - Updated `replace_file()` to fsync the target parent directory after
      `os.replace()` where supported, while preserving temp cleanup behavior.
    - Added focused regressions for corrupt wrapper fields, unsafe index keys,
      malformed stage artifact refs, corrupt-document path messages, and
      parent-directory fsync.
  - Tests or validation re-run:
    - `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=/home/samcantrill/work/loom-worktrees/add-local-stores-run-layout/src uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py tests/unit/loom/pipeline/stores/test_indexes.py tests/unit/loom/pipeline/stores/test_atomic.py` — passed, 25 passed.
    - `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=/home/samcantrill/work/loom-worktrees/add-local-stores-run-layout/src uv run pytest tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py` — passed, 42 passed.
    - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores tests/unit/loom/pipeline/stores/test_local_runs.py tests/unit/loom/pipeline/stores/test_atomic.py` — passed.
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/stores tests/unit/loom/pipeline/stores/test_local_runs.py tests/unit/loom/pipeline/stores/test_atomic.py` — passed, 0 errors.
    - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` — passed; Ruff passed,
      Pyright passed, default pytest passed with 306 passed, and `uv build`
      produced source and wheel distributions.
    - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` — passed and wrote
      `build/test-summary.md`: package passed, unit passed, contract passed,
      integration passed, e2e not present.
  - Remaining blockers: none known after the user-authorized post-review fix.
- Remaining blockers: none.
