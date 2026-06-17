# Configuration Example Coverage

This document tracks configuration functionality covered by current examples.
Examples stay domain-neutral, use public Python APIs, and avoid promising CLI,
remote, plugin, sweep, `_copy_`, or persistence behavior that is outside the
configuration example surface.

## Behavior To Document

| Capability | User-facing behavior to show |
| --- | --- |
| Basic composition | Load a base YAML file and read `resolved`, `unresolved`, and `redacted` views. |
| Overlays | Apply one or more overlays and show later overlays overriding earlier values. |
| `_replace_` | Replace a mapping intentionally and show that the marker is consumed. |
| File includes | Include reusable local YAML fragments with explicit relative paths. |
| Nested includes | Include a file that includes another file relative to the including file. |
| User include replacement | Swap an existing include target through an override and preserve local customizations. |
| Brand-new include addition | Add a new include site with `+..._include_=./path.yaml`. |
| Ordinary overrides | Update existing values, add new values, and show strict failure behavior in comments or tests. |
| Recipes | Register a trusted local recipe and expand `_recipe_` blocks into plain config. |
| Recipe manifests | Print or inspect recipe manifest records for reviewability. |
| Interpolation | Resolve config-node interpolation after composition and overrides. |
| `oc.env` resolver | Use the supported environment resolver while documenting that resolver outputs are not persisted by default. |
| Redaction | Show secret-like values in `resolved` and redacted markers in `redacted`/artifacts. |
| Source artifacts | Inspect metadata-only source records for base, overlays, includes, and recipes. |
| Fingerprints | Compare artifact-safe fingerprints across two compositions. |
| Raw source snapshots | Opt in to raw source snapshots and show that the default is metadata-only. |
| Target instantiation | Keep `_target_` config inert during composition, then explicitly instantiate trusted targets. |
| Nested target graphs | Construct objects with nested `_target_`, `_args_`, `_partial_`, and `_inject_`. |
| Project CLI argv shorthand | Show project-owned CLI argv parsed through `compose_config_from_argv`, including scoped overlays, passthrough args, and warnings without implying a first-party `weave` executable. |
| Error handling | Catch structured config errors and inspect context fields. |
| Import boundaries | Demonstrate that target instantiation can be used separately from YAML composition. |

## Current Examples

| Example | Functionality covered | Implementation notes |
| --- | --- | --- |
| `config-composition.basic` | Base YAML, overlays, ordinary overrides, `resolved`/`unresolved`/`redacted`. | Existing runnable smoke example using `compose_config`; no recipes or includes. |
| `config-composition.includes` | Explicit relative include, nested include, user include replacement, brand-new include addition. | Existing runnable smoke example with a small `configs/` tree and printed source artifact paths. |
| `config-composition.replacement-overlays` | Multi-overlay order and `_replace_` marker semantics. | Runnable smoke example showing overlay 2 replacing overlay 1's mapping. |
| `recipes` | Trusted recipe registration, recipe expansion, interpolation, recipe manifest, redaction. | Existing runnable example; keep as the canonical recipe example. |
| `artifact-safety` | Provenance metadata, source artifacts, artifact-safe fingerprints, resolver facts, raw snapshot default/opt-in. | Runnable smoke example that avoids printing secrets and compares two fingerprints. |
| `target-instantiation` | Nested `_target_` graph, `_args_`, `_partial_`, `_inject_`, explicit instantiation after composition or direct config. | Existing runnable example; extend only if needed for composed handoff. |
| `project-cli-argv` | `compose_config_from_argv`, command validation, scoped overlays, add/update semantics, passthrough args, and helper-local warnings. | Runnable smoke example for project-owned CLI adapters; it must not document or imply a `weave` console command. |
| `config-composition.errors` | Structured exceptions for missing include, invalid override, unsupported resolver, unsupported `_copy_`. | Existing runnable smoke example catches errors and prints context summaries. |

## Example Coverage Checks

Each runnable example should have:

- an `example.yaml` manifest with `status: runnable`;
- one Python entrypoint validated by `packages/weave/tests/test_examples.py`;
- a README that says which public API is used;
- no CLI commands except repository-local `uv run python ...` execution;
- no remote includes, plugin discovery, global search, sweeps, `_copy_`, or
  implicit persistence claims.

## Existing Examples

| Existing example | Current coverage | Notes |
| --- | --- | --- |
| `config-composition.basic` | Base YAML, overlays, ordinary update and add overrides, `resolved`/`unresolved`/`redacted`. | Keep as the canonical first composition example without recipes or includes. |
| `config-composition.includes` | Explicit relative include, nested include relative to the including file, user include replacement, brand-new include addition, include source artifacts. | Keep as the canonical include composition example; broaden only if source snapshot examples need a shared tree. |
| `config-composition.replacement-overlays` | Multi-overlay order and `_replace_` mapping replacement through public `compose_config`. | Keep as the canonical replacement overlay smoke example. |
| `recipes` | Recipes, overlays, ordinary overrides, interpolation, redaction, recipe manifest, fingerprint. | Keep; optionally add one source artifact print once docs want artifact reviewability in examples. |
| `artifact-safety` | Provenance metadata, source artifacts, artifact-safe fingerprint comparison, `oc.env` resolver facts, redaction, metadata-only snapshot defaults, and raw snapshot opt-in. | Keep output concise and avoid printing raw snapshot content or resolved secret values. |
| `target-instantiation` | Direct nested target instantiation with `_args_`, `_partial_`, and `_inject_`. | Keep; add a composed-target handoff example only if a separate example would not be clearer. |
| `project-cli-argv` | Project-owned CLI argv shorthand through `compose_config_from_argv`, scoped overlays, add/update scoped overlay behavior, ordinary overrides, passthrough command args, and warnings. | Keep clear that `weave` exposes Python helpers, not a first-party executable or Loom CLI behavior. |
| `config-composition.errors` | Missing include, invalid include override, unsupported resolver, unsupported `_copy_`, and structured context summaries. | Keep as the canonical config error-handling smoke example. |
| `execution.local` | Pipeline execution using composed plain config. | Keep under execution examples; do not use it as config artifact evidence. |
