# Expanded V0 Implementation Plan For `loom`

## Summary

Implement v0 as a source-tree-first, fully typed Python package aligned with the design boundaries in `docs/structure.md`. The full long-term package layout should be present where already chosen, but runnable behavior should focus on the local pipeline path. Keep `loom` generic: it describes, configures, constructs, runs, resumes, and tracks artifact-based workflows. Domain packages supply concrete stages, recipes, codecs, and data semantics.

The v0 acceptance target is: compose trusted YAML config, expand recipes, instantiate user stage targets, validate a local artifact DAG, run it in-process, persist an inspectable run directory, and resume unchanged stages from the same run directory using strict fingerprints.

Key decisions locked in:

- Use the full target package tree with import-safe stubs for deferred features.
- Use hard config dependencies: OmegaConf, Pydantic v2, and YAML support.
- No functional CLI in v0; CLI modules may exist as import-safe stubs only.
- Use `loom.records` and `loom.provenance` as packages, not top-level files.
- Require `uv run pytest`, `uv run ruff check .`, and `uv run pyright` to pass.

## Key Changes

- Package foundation:
  - Keep the setup scaffold passing `make check` and `uv build`.
  - Add hard runtime dependencies for config support when config implementation begins.
  - Replace the initial metadata-only package surface with stable public exports for `ResourceRef`, `ArtifactRef`, `Record`, `InMemoryManifest`, `ManifestView`, `Fingerprint`, and `hash_mapping`.
  - Keep `loom.__init__` cheap and safe: no config composition, pipeline runners, CLI, plugin discovery, or expensive optional imports.
  - Populate the selected long-term package layout with typed modules. Deferred modules must import cleanly and raise clear unsupported-feature errors only when called.
  - Keep domain code out of `loom`; extension points use protocols, registries where names need resolution, and `_target_` construction.

- Core primitives:
  - Implement `ids`, `refs`, `artifacts`, `records`, `provenance`, `fingerprints`, `protocols`, `errors`, and `timestamps` as the public vocabulary layer.
  - Use frozen typed dataclasses for `ResourceRef`, `ArtifactRef`, `Record`, provenance records, output specs, status records, and planning/execution result types.
  - Preserve the distinction between checksums and fingerprints everywhere: checksum is stored bytes identity; fingerprint is semantic production identity.
  - Keep package-wide protocols minimal. Put subsystem contracts such as `Stage`, `Codec`, `DataSource`, `ArtifactStore`, and `RunStore` in their subsystem packages.

- Serialization and I/O:
  - Keep `serialization` limited to Python objects to plain structured data: dataclass conversion, stable JSON, schema-version checks, and serialization errors.
  - Do not put file opening, URI handling, codecs, stores, or artifact layout inside `serialization`.
  - Keep `io` focused on bytes, files, URIs, sources, and codecs. Implement URI helpers, `LocalFileSystemSource`, JSON/text/bytes codecs, and explicit codec registry.
  - Use registries only where a stable name must resolve to behavior: recipe name, codec key, source scheme later, executor name later.
  - Do not add domain codecs or remote storage backends in v0.

- Config system:
  - Implement `compose_config(config_path, overlays=(), overrides=(), recipe_catalog=None)` returning `ComposedConfig(resolved, redacted, provenance, fingerprint)`.
  - Composition order: load base config, load overlays, recursive merge, apply dot-path overrides, resolve enough interpolation for recipe args, expand recipes, resolve interpolation again, validate, redact, compute config provenance.
  - Merge policy is deliberately simple: mapping plus mapping recursively merges, scalar replaces scalar, list replaces list, and `null` is an explicit value.
  - Implement YAML loading, OmegaConf interpolation, dot-path override parsing, top-level validation, missing-value checks, recursive redaction, redacted resolved config export, and full config provenance.
  - Implement real `_recipe_` support using an explicit in-process/local `RecipeCatalog`: registration, lookup, typed construction, expansion, validation, clear errors, and recipe provenance.
  - Implement recursive `_target_` construction with import path validation, `_args_`, `_partial_`, `_inject_`, explicit runtime injection, recursive kwargs, and path-aware target errors.
  - Treat configs as trusted code; no allow-list mode in v0.
  - Do not implement include graphs, Hydra defaults, registry aliases for arbitrary components, expression language, arbitrary schema inference, advanced list patching, or plugin entry-point discovery.

- Pipeline runtime:
  - Standardize on the inline stage config shape:

    ```yaml
    pipeline:
      stages:
        - name: build
          _target_: project.stages.BuildStage
          config:
            limit: 100
          outputs:
            index:
              artifact_type: json
              codec_key: json.v1

        - name: report
          _target_: project.stages.ReportStage
          depends_on: [build]
          inputs:
            index: build.index
          outputs:
            report:
              artifact_type: text
              codec_key: text.v1
    ```

  - Parse only orchestration fields into `StageSpec`: `name`, `depends_on`, `inputs`, `outputs`, `resources`, `_target_`, and `config`.
  - Pass only the stage `config` mapping as constructor kwargs to the stage target.
  - Require declared output specs: every output name maps to `artifact_type` and `codec_key`.
  - Input bindings use only `stage.output`; input refs create data dependencies, while `depends_on` adds control dependencies.
  - Validate unique stage names, existing output references, acyclic graph, topological order, declared outputs, and upstream-only input bindings.
  - Stage implementations are structural protocol implementations, not subclasses:

    ```python
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]: ...
    ```

  - Stages save artifacts through:

    ```python
    context.artifact_store.save(
        obj,
        name="index",
        artifact_type="json",
        codec_key="json.v1",
        metadata={},
    )
    ```

  - `StageContext` exposes run/stage identity, paths, resolved config, metadata, stores, and a stage-bound artifact writer.
  - Runner owns lifecycle, planning, validation, status, fingerprints, output validation, `outputs.json`, and resume decisions.

- Stores, planning, and execution:
  - Implement `ArtifactStore` and `RunStore` protocols plus `LocalArtifactStore` and `LocalRunStore`.
  - Local stores must be human-inspectable and use atomic writes for status, inputs, outputs, fingerprints, provenance, and artifact indexes.
  - Expected run layout includes `config/`, `stages/<stage>/status.json`, `inputs.json`, `outputs.json`, `fingerprint.json`, `provenance.json`, `artifacts/<stage>/`, top-level `run.json`, and `provenance/`.
  - Keep planning separate from execution. `PipelinePlanner` computes bindings, fingerprints, run/skip decisions, invalidated downstream stages, and resume eligibility.
  - `PipelineRunner` coordinates: create run directory, write config/provenance, validate pipeline, ask planner for an execution plan, execute stages through `LocalExecutor`, update lifecycle records, validate returned artifacts, and finalize run status.
  - Resume works only against the same run directory. A stage can skip only when prior status is `SUCCEEDED`, fingerprint matches, `outputs.json` exists, all declared artifacts exist, and checksums validate when present.

- Fingerprints:
  - Include stage name, target path, constructor config, declared output specs, bound input `ArtifactRef`s, Python version, `loom` version, relevant git state, configured dependency versions, and configured extra fingerprint fields.
  - Do not include noisy values such as wall-clock timestamps, log paths, temp paths, or random run IDs unless explicitly configured because they affect output semantics.
  - Capture broader environment provenance where practical, but only the configured dependency list affects skip/rerun decisions.
  - Treat inconsistent or interrupted state as not reusable.

- Error model and import boundaries:
  - Add a top-level `LoomError` hierarchy with broad catchable classes and specific errors in the subsystem that raises them.
  - Make config, pipeline, store, serialization, and instantiation errors path-aware. Include config path, stage name, artifact name, target path, and file path where relevant.
  - Add tests to enforce public import stability and dependency direction: primitives do not import pipeline, serialization does not import I/O, pipeline does not import CLI, and `loom` does not import domain packages.

## Implementation Phases

1. Foundation:
   - Confirm setup gates pass.
   - Add config dependencies.
   - Replace package metadata-only exports.
   - Add common errors, timestamps, identifiers, import-safe package skeleton, and public import tests.
   - Add tests proving deferred stubs import cleanly and fail only when called.

2. Primitives and serialization:
   - Implement refs, artifacts, records/manifests, provenance models, stable fingerprints, plain-data conversion, dataclass helpers, JSON helpers, and schema/version errors.
   - Add tests for serialization determinism, dataclass conversion, schema-version failures, checksum/fingerprint behavior, and public API stability.

3. I/O basics:
   - Implement URI normalization, local source, codec protocol, JSON/text/bytes codecs, and codec registry.
   - Add tests for file URI conversion, local source `open`/`exists`/`stat`/`glob`, codec round trips, registry duplicate handling, and unknown codec errors.

4. Config composition:
   - Implement config loading, merge semantics, override parsing and application, OmegaConf interpolation wrapper, top-level validation, redaction, config provenance, and `compose_config`.
   - Add tests for base plus overlays, list replacement, explicit null, parsed override types, interpolation, missing values, redaction by key pattern, and config provenance hashes.

5. Recipes and instantiation:
   - Implement recipe protocol/model, explicit `RecipeCatalog`, `register_recipe`, recursive expansion, expansion provenance, and path-aware recipe errors.
   - Implement target importing, recursive instantiation, `_args_`, `_partial_`, `_inject_`, runtime dependency validation, reserved-key validation, and path-aware constructor errors.
   - Add tests for nested recipes, unknown recipes, recipe validation failures, bad targets, bad constructor args, partial construction, and runtime injection.

6. Pipeline specs and graph:
   - Implement `PipelineSpec`, `StageSpec`, `OutputSpec`, `Stage` protocol, `StageContext`, pipeline status types, graph construction, binding parser, topology, and generic validation.
   - Add tests for inline stage parsing, duplicate names, missing outputs, bad `stage.output` refs, cycles, topological order, and upstream/control dependency semantics.

7. Stores and planning:
   - Implement `ArtifactStore`, `RunStore`, `LocalArtifactStore`, `LocalRunStore`, artifact indexes, low-level atomic writes, stage/run status records, fingerprint calculation, and `PipelinePlanner`.
   - Implement resume checks, changed-stage invalidation, downstream invalidation, and treatment of interrupted or corrupt stage state.
   - Add tests for atomic writes, artifact save/load, output metadata, status transitions, resume eligibility, checksum validation, missing artifacts, config-change reruns, and downstream invalidation.

8. Local execution:
   - Implement `LocalExecutor`, lifecycle helpers, and `PipelineRunner`.
   - Runner must create run dirs, persist config/provenance, instantiate stages, bind inputs, execute stages, validate output names/types/codecs/existence, write stage status, write run status, and surface failure details.
   - Add a synthetic E2E pipeline: `write -> add -> multiply -> report`.

9. Hardening:
   - Improve path-aware error formatting.
   - Add interrupted-run recovery tests for stale `RUNNING`, missing `outputs.json`, partial artifacts, and corrupt JSON.
   - Add import-direction tests and extension-point contract tests for dummy stages, codecs, stores, and recipes.
   - Add README/docs snippets documenting trusted configs, stage contract, artifact saving, and same-run-dir resume.

## Test Plan

- Unit tests:
  - Primitive construction, public imports, and plain-data serialization.
  - Stable fingerprint determinism and checksum/fingerprint separation.
  - Dataclass conversion, schema-version checks, and stable JSON output.
  - URI helpers, local source behavior, codec round trips, and codec registry errors.
  - Config load, merge, overrides, interpolation, validation, redaction, and provenance.
  - Recipe registration, expansion, validation, provenance, and unknown recipe errors.
  - Target import, recursive instantiation, `_args_`, `_partial_`, `_inject_`, and bad constructor errors.
  - Pipeline spec parsing, DAG validation, graph order, input binding, output spec validation, and stage output validation.
  - Artifact/run store atomic writes, artifact indexes, status transitions, resume decisions, and corrupt state handling.

- E2E tests:
  - Run synthetic local pipeline from YAML.
  - Verify run directory contains raw/resolved/redacted config where applicable, recipe manifest, provenance, status files, fingerprints, inputs, outputs, and artifact refs.
  - Rerun same run directory and verify unchanged stages skip.
  - Change stage config and verify that stage plus downstream dependents rerun.
  - Change an upstream artifact-producing stage and verify downstream invalidation.
  - Simulate missing artifact files and verify reuse is refused.
  - Return an undeclared or wrong-type output and verify runner fails with a path-aware error.
  - Simulate a stage failure and verify status/provenance are written and the run fails cleanly.

- Acceptance gates:
  - `uv run pytest`
  - `uv run ruff check .`
  - `uv run pyright`

## Assumptions

- Python remains `>=3.12`.
- Pyright must pass, but strict mode is deferred.
- No functional CLI, subprocess executor, SLURM executor, sweeps, plugins, remote stores, global run discovery, or cross-run cache index in v0.
- CLI modules may exist only as import-safe stubs.
- No path templates for outputs; physical paths are owned by the artifact store.
- No output path interpolation or interpolation-style artifact refs.
- No local lock manager in v0 unless required by tests; atomic writes are required.
- No domain stages, codecs, recipes, schemas, datasets, model code, or analysis assumptions are added to `loom`.
- Configs are trusted code; no sandbox or allow-list mode in v0.
- Deferred features should be represented by clear unsupported-feature errors, not silent no-ops.
- Public imports should remain stable even if internals are later refactored.
