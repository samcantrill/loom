# V0 Public API Migration Notes

The v0 implementation was hardened so that several early contract patterns were
replaced with explicit, inspectable, and composable surfaces.
The table below maps changed behavior for migration planning.

## API and Contract Migration Notes

| Removed / Deprecated Shape | Replacement |
| --- | --- |
| Stage mappings with top-level stage `_target_` and constructor-style keys mixed into stage `config` | `factory: {_target_: ..., init: {...}}` for constructor injection, with runtime invocation data in stage `config` |
| Direct stage target values in local run state documents | `StageSpec.factory.target_path` and `StageFactorySpec` as the explicit parsing/validation contract |
| `StageContext` exposing direct `run_dir`/`stage_dir`/store internals | `StageContext` facade with local path helpers (`local_output_path`, `local_workspace_path`) and artifact helpers (`save_artifact`, `register_artifact`, `load_input`, `load_artifact`) |
| Run and artifact lookup by opaque local path arguments in runtime contracts | Capability-oriented store APIs (`RunStore`, `ArtifactStore`) plus explicit local path helpers only as convenience |
| Shared global artifact refs without run identity | `ArtifactAddress(run_id, artifact_id)` for explicit run-aware identity |
| Shared mutable process-global recipe state as the only composition path | Explicit `RecipeCatalog` with `compose_config_with_catalog`, with optional `register_recipe` remaining for simple single-script use |
| Legacy stage config assumptions that mix constructor/runtime fields | Separate constructor init (`factory.init`) from runtime `config`/`stage_config` |

## Closeout Notes

- V1 implementation planning should start from this v0-post contract baseline.
- These migrations are now documented in:
  - `docs/loom.md`
  - `docs/features/config.md`
  - `docs/features/pipeline.md`
  - `docs/structure.md`
- Public docs and tests should not re-introduce deferred pre-hardening assumptions.

