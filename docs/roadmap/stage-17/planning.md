# Roadmap Stage 17 Planning: Docker Container Executor

## Metadata

- Roadmap stage: v17
- Source roadmap: `docs/roadmap.md`
- Previous version status:
  - `docs/roadmap/stage-16/planning.md` exists and records confirmed Stage 16
    planning for artifact payload materialization.
  - `docs/roadmap/stage-16/implementation-plan.md` exists in the current
    checkout and records Stage 16 complete with all phases merged and no known
    blocker.
- Planning artifact status: confirmed
- Current discussion stage: implementation-plan drafting
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Capability triage and candidate functional requirements: confirmed
  - Functionality agreement review: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: completed
  - Design agreement review: confirmed
  - Design safety review: completed
  - Examples and validation strategy: completed
  - Phase shaping: completed
  - Implementation readiness: completed
  - Handoff: prepared
- Related implementation plan: `docs/roadmap/stage-17/implementation-plan.md`
- Related feature docs:
  - `docs/features/container-executors.md`
  - `docs/features/execution.md`
  - `docs/features/runtime-resources.md`
  - `docs/features/preflight.md`
  - `docs/features/provenance.md`
  - `docs/features/reliability.md`
  - `docs/features/testing.md`
- Blockers:
  - None in the planning artifact.
  - Final user confirmation received on 2026-05-16; implementation-plan
    drafting may proceed from this artifact.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` v17 | Stage 17 adds a Docker-based container executor that reuses the stage-worker and store contracts. It includes shared container config models, Docker CLI command builder/executor, environment filtering, redaction, mount/workdir/run-dir/artifact-root checks, provenance, logs, exit-code and timeout metadata, preflight, and fake-command tests. | roadmap scope | Docker is the only concrete container runtime in v17. |
| `docs/roadmap.md` v17 | Exit criteria require a stage to run through Docker with the same declared inputs/outputs and run-store semantics as local and subprocess execution; Docker failures must be inspectable through existing diagnostics; no Docker SDK dependency is required. | acceptance boundary | The first implementation should be CLI-backed and testable without a real Docker daemon by default. |
| `docs/roadmap.md` v17 | Defers image build commands, registry authentication helpers, Docker Compose, Kubernetes, automatic image pulls during preflight, image lock files, advanced GPU mapping, Apptainer/Singularity, and treating containers as a security sandbox. | explicit deferrals | Prevents the stage from becoming a broad container platform. |
| `docs/roadmap.md` v18 | Stage 18 owns Apptainer/Singularity and SLURM plus Apptainer composition. | successor boundary | Stage 17 may create shared container records, but should not implement HPC runtime behavior. |
| `docs/features/container-executors.md` | Container executors should preserve the same stage execution contract, work with local run directories and artifact stores, record image/runtime provenance, avoid normal-use container requirements, and keep command construction inspectable. | behavior baseline | Supports per-stage Docker execution over whole-pipeline containerization as the likely default. |
| `docs/features/container-executors.md` | Docker responsibilities are to find the Docker command, construct `docker run`, apply mounts/workdir/environment/resources, capture stdout/stderr, record exit code, and record image digest when available. | Docker executor shape | The feature doc recommends Docker CLI over the Python SDK. |
| `docs/features/container-executors.md` | Required mounts usually include project source or installed package, run directory, artifact store root for local stores, and temp directory when needed; run directory must be writable. | mount and artifact behavior | This directly affects preflight and runtime failure semantics. |
| `docs/features/container-executors.md` | Container execution should be explicit about trust: do not pass all host environment variables, redact secrets, avoid privileged containers, reject unsafe mount targets, and do not call it a security sandbox without a separate threat model. | security/trust boundary | Authored configs remain trusted, but persisted metadata must be redaction-safe. |
| `docs/features/runtime-resources.md` | Container executors map environment and mounts, may map resources when the runtime supports them, and record image identity and command. The default fingerprint policy treats operational choices as provenance unless explicitly marked semantic. | runtime/resource policy | Resource support and semantic fingerprinting need explicit planning choices. |
| `docs/features/provenance.md` | Container metadata should record image, digest, and runtime without depending on concrete executor implementations. | provenance shape | Docker metadata should nest in executor metadata rather than changing core provenance ownership. |
| `docs/features/preflight.md` and `src/loom/diagnostics/preflight.py` | Preflight already has executor, resources, filesystem, artifact backend, subprocess, and SLURM checks; stable check IDs are enumerated in diagnostics models. | diagnostics integration | Stage 17 likely adds Docker-specific executor/filesystem/resource checks without making image pulls default. |
| `docs/features/testing.md` and `docs/features/container-executors.md` | Default tests should use fake commands and command builders; real Docker/Apptainer tests should be optional and skipped unless explicitly enabled. | validation strategy | Core validation must be local, deterministic, synthetic, and network-free. |
| `docs/structure.md` | `loom.pipeline.execution` coordinates runner lifecycle; `loom.pipeline.executors` owns stage invocation mechanisms; executors must not own DAG semantics, resume policy, config composition, or artifact indexes. | architecture boundary | Docker belongs in executor-adapter code and should consume execution/store contracts. |
| `docs/GLOSSARY.md` | `executor` is the component that runs one stage through a backend; distinguish it from `PipelineRunner`. `LocalRunStore` is local filesystem materialization, not authority truth. | vocabulary | Keeps Docker planning aligned with existing terminology. |
| `docs/roadmap/stage-5/implementation-plan.md` | Stage 5 created the durable stage-worker contract and subprocess executor so future schedulers/containers can invoke one prepared stage from durable state. | prerequisite | Docker should reuse the worker command rather than creating a second runner. |
| `docs/roadmap/stage-7/implementation-plan.md` | SLURM live operations added submitted lifecycle patterns and fake command runners while keeping scheduler-specific payloads under the SLURM executor. | adjacent executor precedent | Useful precedent for backend-specific command abstractions and cluster-free tests. |
| `docs/roadmap/stage-15/implementation-plan.md` | External artifact records and backend contracts are complete; Stage 17/18 are future consumers of artifact facts without requiring Stage 15 payload movement. | artifact prerequisite | Docker must not bypass artifact-store records or invent external payload semantics. |
| `docs/roadmap/stage-16/implementation-plan.md` | Stage 16 exposes explicit materialization and operation evidence; Stage 17/18 can use copy materialization and derived staging facts for container/HPC payload placement. | artifact payload prerequisite | Docker may need explicit local materialization/staging decisions for container mounts. |
| `src/loom/pipeline/execution/stage_worker.py` | `run_stage_worker` reconstructs one prepared stage attempt from durable state and writes a worker result handoff. | current source boundary | Docker should likely run the existing `loom stage run --run-uri ... --stage ... --attempt ...` path inside the container. |
| `src/loom/pipeline/executors/subprocess.py` | `SubprocessExecutor` builds the stage-worker command, launches a process through an injectable runner, reads worker results, and normalizes process metadata/failure conflicts. | implementation precedent | Docker can mirror the command-runner/testability shape while substituting Docker CLI command construction. |
| `src/loom/pipeline/runtime/capabilities.py` | The default descriptor registry includes `local`, `subprocess`, `slurm-single-job`, and `slurm-afterok`; resource capabilities are descriptor-owned and adapter namespaces are explicit. | current runtime state | Stage 17 must add Docker descriptor/resource behavior or explain a plugin registration path. |
| `src/loom/cli/run.py` | `loom run` currently recognizes local, subprocess, and SLURM flows; unsupported executor messaging still lists local/subprocess in one error path. | CLI integration gap | Docker CLI selection must update run/preflight resolution without broad CLI churn. |
| `src/loom/pipeline/runtime/profiles.py` | Runtime profiles normalize unknown profile-level fields into `adapter_options` namespaces and support per-stage `adapter_options`. | design-pass config ownership | Supports runtime/profile adapter-owned Docker or shared container configuration without changing semantic pipeline stage specs. |
| `src/loom/pipeline/runtime/environment.py` | Run and stage environment requests currently store explicit set/unset variables and safe metadata counts. | design-pass environment handoff | Docker should reuse explicit environment data but must not persist raw values in executor metadata. |
| `src/loom/pipeline/execution/runner.py` | Executors with `requires_prepared_worker_request` cause the runner to prepare durable worker requests, mark stages running, call the executor, then parent-finalize results. | design-pass executor lifecycle | Docker can reuse the subprocess lifecycle path instead of adding a new runner mode. |
| `src/loom/pipeline/executors/slurm/commands.py` | SLURM uses a fakeable command-runner protocol and bounded command-result records. | design-pass command runner precedent | Docker should follow the fakeable runner pattern for deterministic default tests. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Roadmap and workflow docs | `.codex/workflows/roadmap-stage-planning.md`, `.codex/prompts/roadmap-stage-planning-facilitate.md`, functionality/design/design-safety prompts, `.codex/templates/roadmap-stage-planning.md`, `docs/roadmap.md` v16-v18 | Workflow requires startup briefing, clarification gate, then capability triage. V17 is Docker-first and defers HPC container composition. | None for startup. |
| Feature docs | `container-executors.md`, `runtime-resources.md`, `provenance.md`, `preflight.md`, `testing.md`, plus `docs/loom.md`, `docs/structure.md`, `docs/GLOSSARY.md` | Feature docs support per-stage Docker execution, explicit config, CLI-backed command building, mount/workdir validation, redaction, opt-in image pulls, fake-command tests, and no sandbox guarantee. | Design-safety review reread the container, runtime-resource, preflight, provenance, and reliability boundaries; no additional feature-doc blocker found. |
| Source and tests | `src/loom/pipeline/executors/base.py`, `subprocess.py`, executor package exports, `src/loom/pipeline/execution/stage_worker.py`, `runner.py`, `src/loom/pipeline/runtime/capabilities.py`, `profiles.py`, `environment.py`, `src/loom/diagnostics/preflight.py`, `src/loom/diagnostics/models.py`, `src/loom/pipeline/stores/artifact_materialization.py`, `src/loom/pipeline/executors/slurm/commands.py`, executor/runtime/preflight tests by file listing | Current source has durable stage-worker, subprocess, SLURM, runtime descriptor registry, profile adapter namespaces, preflight check IDs, fakeable command-runner precedent, and Stage 16 materialization records. No Docker executor module or Docker descriptor exists yet. | None for planning; implementation planning should turn the completed examples, validation strategy, and phase sketch into phases. |
| Prior or adjacent plans | Stage 5, Stage 7, Stage 15, Stage 16 implementation plans; Stage 16 planning startup | Stage 5 supplies the worker contract; Stage 7 supplies fake command/manifest precedent; Stage 15/16 supply artifact metadata and materialization boundaries. | Stage 18 has no plan yet, so future compatibility comes from `docs/roadmap.md` and `container-executors.md`. |

## Roadmap Extraction

Baseline roadmap outcome:

- Add a Docker CLI-backed container executor that can run one prepared stage
  attempt through the existing stage-worker and run-store contracts.
- Provide shared container configuration records for image, workdir, mounts,
  selected environment, and supported resource mappings in a shape that can be
  reused by Stage 18 without implementing Apptainer or SLURM-container
  composition early.
- Record redacted Docker command, logs, image/runtime provenance, exit-code
  and timeout-related facts where available, and failure metadata that existing
  diagnostics can inspect.
- Add Docker-specific preflight for command availability, image reference
  presence, mount sources, run-directory writability, artifact-root mounting,
  required environment variables, and resource support.
- Validate command construction, mount/workdir safety, environment filtering,
  redaction, resource flags, exit-code mapping, and provenance with fake
  command tests by default.

Prerequisites:

- Stage 5 durable stage-worker and subprocess execution contracts.
- Stage 4 runtime options, stage options, environment, resources, executor
  descriptors, and capability diagnostics.
- Stage 3 preflight and diagnostics presentation.
- Stage 15 artifact-store records and backend capability contracts.
- Stage 16 materialization/staging operation records for payload movement and
  local artifact placement where a container mount needs host-visible bytes.
- Current local/subprocess/SLURM executor registration and CLI selection paths.

Primary feature docs:

- `container-executors.md`
- `execution.md`
- `runtime-resources.md`
- `preflight.md`
- `provenance.md`
- `reliability.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Image build commands.
- Registry authentication helpers.
- Docker Compose.
- Kubernetes or cloud container orchestration.
- Automatic image pulls during default preflight.
- Image lock files.
- Advanced GPU mapping.
- Apptainer/Singularity and SLURM-container composition.
- Treating containers as a security sandbox for untrusted code.
- Broad retry/timeout policy beyond recording available timeout metadata unless
  a minimal executor-local timeout behavior is explicitly confirmed.

Future-roadmap touchpoints:

- Stage 18 should reuse shared container config, mount, environment, resource,
  provenance, redaction, command-builder, and fake-command test patterns for
  Apptainer/Singularity and SLURM-container composition.
- Stage 19 can wrap container execution with shared retry, timeout,
  failure-category, transaction, status-detail, and retry-safety policy.
- Stage 20 can project committed Docker/container facts into runtime events and
  observe-only event sinks.
- Stage 21 can use derived materialization/staging/log records for
  conservative cleanup without deleting authority truth or external artifact
  payloads.
- Future executor plugin or adapter work should be able to register Docker-like
  executor descriptors without importing Docker behavior at package import time.

Compatibility obligations:

- Local and subprocess execution semantics must remain unchanged.
- Docker execution must use the same declared inputs, outputs, result handoff,
  run-store status, artifact-store contracts, and diagnostics conventions as
  local and subprocess execution.
- Default install and import paths must not require Docker, Docker SDK, a
  running daemon, network access, or image registry access.
- Default tests must not require a real Docker daemon.
- Persisted command/provenance/diagnostic data must redact secret-looking
  environment values and avoid serializing unsafe host environment details.
- Operational container choices should be provenance facts by default, not
  semantic fingerprint inputs, unless a later design explicitly chooses a
  semantic policy.

## Stage Briefing

What this stage is:

- Stage 17 is Loom's first container-execution stage. It should make
  `--executor docker` capable of running prepared stage attempts through
  Docker while preserving Loom's existing stage-worker, run-store,
  artifact-store, logging, failure, and diagnostics behavior.
- The stage is specifically Docker-first. Shared container concepts should be
  reusable, but Apptainer/Singularity, SLURM-container composition, image
  building, registries, Compose, Kubernetes, and security-sandbox promises are
  outside this stage.

Why this stage exists:

- Local and subprocess execution prove Loom's stage contract on the host.
  SLURM proves scheduler command generation and live submission. Stage 17
  fills the local reproducible-environment gap: run the same prepared stage
  command in a selected image, with explicit mounts and environment handoff,
  while keeping the controller and run-store semantics in Loom.
- Docker is a useful first container runtime because its command surface is
  common in local development and CI, and it can be tested through command
  builders/fake runners without adding a Docker Python SDK or making Docker a
  default dependency.

Impacted or linked work:

- `loom.pipeline.execution` should keep lifecycle ownership: prepare the stage
  attempt, invoke the executor, validate the worker result, commit outputs, and
  persist final status.
- `loom.pipeline.executors` likely gains shared container records/helpers and a
  Docker executor module. The Docker executor should adapt backend invocation
  only; it should not own DAG semantics, resume policy, config composition, or
  artifact indexes.
- `loom.pipeline.runtime` likely gains a Docker executor descriptor and
  container or Docker adapter option parsing/validation.
- `loom.diagnostics.preflight` likely gains Docker command, image reference,
  mount, writable-run-dir, environment, and resource checks. Image pulls and
  registry contacts should stay opt-in or out of scope.
- `loom.cli.run` should recognize Docker as a selected executor and still act
  as a thin presentation layer.
- `loom.pipeline.stores` and Stage 16 materialization records are relevant
  when local artifact payloads or run directories need host-visible paths that
  can be mounted into a container.

Likely public surfaces and durable artifacts:

- Public Python records for container config: image, workdir, mounts, selected
  environment variables, resource mapping policy, and safe command projection.
- A Docker executor class and command builder using the Docker CLI.
- Runtime descriptor entries and possibly adapter namespace keys for Docker or
  shared container options.
- CLI selection through `loom run CONFIG --executor docker`, plus preflight
  coverage for the same executor.
- Persisted executor metadata including redacted command, Docker runtime
  version when cheaply available, image reference, digest when cheaply
  available, mount summaries, environment key summaries, exit code, log paths,
  and failure details.
- Stable preflight check IDs for Docker command availability, mount/workdir
  safety, run/artifact-root writability, and supported resource mappings.

Structure rationale:

- The planning structure should first confirm the user-visible Docker workflow
  and hard non-goals because the feature sits at the intersection of executor
  behavior, runtime config, filesystems, provenance, diagnostics, and security
  language.
- Capability triage should separate included Docker execution behavior from
  tempting but deferred container-platform behavior, especially image builds,
  registry auth, automatic pulls, Compose/Kubernetes, Apptainer, and sandbox
  claims.
- The later design pass must be careful about reusable container contracts.
  Stage 17 should be generic enough for Stage 18 to reuse, but not so generic
  that it commits Loom to premature scheduler/container orchestration APIs.

Visible assumptions, risks, and constraints:

- Assumption: the default mode should be per-stage Docker execution using the
  durable `loom stage run --run-uri ... --stage ... --attempt ...` worker path,
  not whole-pipeline containerization.
- Assumption: Docker configuration should live in runtime/profile or adapter
  options rather than in semantic pipeline stage specs, keeping pipeline specs
  portable across executors.
- Assumption: default preflight should not pull images, contact registries, or
  require a running Docker daemon unless the user selects an explicit expensive
  probe.
- Risk: mount path translation can accidentally create a second view of run or
  artifact paths. Planning must decide whether container paths must match host
  paths, whether explicit mapping is allowed, and how stage metadata records
  path facts.
- Risk: environment forwarding can leak secrets if recorded commands or
  metadata include values. The likely default is explicit allowlist/keys-only
  persistence with value redaction.
- Risk: resource mapping, especially GPUs, can become runtime-specific quickly.
  The roadmap defers advanced GPU mapping; Stage 17 should probably support
  basic CPU/memory mappings and either fail closed or record unsupported GPU
  mapping unless a narrow default is confirmed.
- Constraint: authored configs are trusted project code, but container images
  and mounts must not be documented as a sandbox for untrusted code.
- Constraint: Docker support must not add a Python Docker SDK dependency or a
  default test dependency on a real Docker daemon.

User clarification questions and resolved answers:

- The user agreed with the startup briefing recommendations on 2026-05-16.
- Clarifying questions: none raised before moving to intent discovery.
- Confirmed priority: optimize for reliable per-stage Docker executor parity
  with local/subprocess execution, mainly for local development and CI, while
  preserving Stage 18 reuse.
- Confirmed target users: local developers and CI maintainers first, without
  blocking future cluster/container integrator use.

## User Intent

Target audience:

- Local developers and CI maintainers first, with future cluster/container
  integrator compatibility preserved for Stage 18.

User-visible outcome:

- Users can select Docker as an executor for normal Loom runs and get the same
  declared input/output, run-store, artifact-store, log, failure, and
  diagnostics semantics as local/subprocess execution.

Success criteria:

- `loom run CONFIG --executor docker` runs a small local pipeline through the
  existing durable stage-worker path.
- Docker execution preserves the same declared input/output, run-store,
  artifact-store, status, worker-result, log, and failure semantics as local
  and subprocess execution.
- Docker failures are inspectable through existing status, log, failure, and
  diagnostics surfaces.
- Docker preflight catches missing Docker command, missing image config, bad
  mounts, run-directory/artifact-root writability problems, required
  environment-variable gaps, and unsupported resource mappings.
- Default tests use command builders and fake command runners. Any real Docker
  validation is opt-in and skipped by default.
- Examples show both a stage-level Docker execution path and a full Loom
  pipeline whose stages run through Docker executor environments.

Non-goals:

- Image build commands.
- Registry authentication helpers.
- Automatic image pulls during default preflight.
- Docker Compose.
- Kubernetes or cloud container orchestration.
- Apptainer/Singularity and SLURM-container composition.
- Treating containers as a security sandbox for untrusted project code.
- Real Docker daemon dependency in default tests or `make validate-pr`.
- Docker Python SDK dependency.

Constraints:

- Use the Docker CLI rather than the Docker Python SDK.
- Pass mounts explicitly and validate host paths, container targets, modes,
  run-directory writability, and artifact-root visibility.
- Pass environment variables by explicit allowlist or selected runtime
  configuration, not by copying the full host environment.
- Persist redacted command/environment metadata only; do not persist secret
  values.
- Keep image pulls, registry access, daemon-heavy probes, and real Docker
  execution out of default preflight and default tests.
- Preserve a reusable shared container configuration shape for Stage 18 without
  implementing Apptainer/Singularity or SLURM-container behavior early.
- Provide examples of running stages or pipelines in Docker environments,
  interpreted as direct/prepared stage execution examples plus normal Loom
  pipeline runs whose stage attempts execute in Docker containers.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- The artifact has been initialized from the roadmap-stage planning workflow.
- Stage 17 is being treated as Docker-first container execution, with Stage 18
  left to Apptainer/Singularity and SLURM-container composition.
- The user confirmed the recommended roadmap framing: reliable per-stage Docker
  executor parity for local/CI use, preserving reusable container records for
  Stage 18.
- The user did not raise clarifying questions before intent discovery.

Intent discovery locked decisions:

- The user agreed with the recommended intent defaults on 2026-05-16.
- Required success examples are normal Docker execution, inspectable Docker
  failure, and Docker preflight.
- Hard non-goals are image builds, registry auth, automatic pulls,
  Compose/Kubernetes, Apptainer/Singularity, SLURM-container composition, real
  Docker default tests, Docker SDK dependency, and security-sandbox claims.
- Operational constraints are Docker CLI only, explicit mounts, explicit
  environment handoff, redacted persisted metadata, fake-command default
  tests, and Stage 18-compatible shared container records.

Capability triage and candidate-functional-requirement readback:

- The user agreed with the candidate capability sort and FR-1 through FR-9 on
  2026-05-16.
- The user added that Stage 17 should be able to provide examples of running
  stages or pipelines in Docker environments.
- The artifact adds FR-10 for examples and demonstrations. Current default:
  examples should show direct/prepared stage execution and whole pipeline runs
  whose stages use the Docker executor, without adding whole-pipeline
  controller-in-container execution mode.

Functionality-agreement readback:

- The user confirmed on 2026-05-16 that pipeline examples should mean normal
  Loom pipeline runs where selected stage attempts execute through the Docker
  executor, while whole-controller-in-container mode remains deferred.
- FRQ-2 through FRQ-5 are resolved. Per-stage Docker execution is the only
  required execution mode; Docker option/config scope belongs in
  runtime/profile adapter options at the requirement level; default preflight
  must not pull images, handle registry auth, or perform network/daemon-heavy
  probes; examples and demonstrations are explicit Stage 17 functionality.
- FR-1 through FR-10 are accepted as the Stage 17 functional requirement set.

Functionality and behavior confirmation readback:

- The user confirmed the behavior baseline on 2026-05-16.
- Included functionality: per-stage Docker execution for selected stage
  attempts during normal Loom runs; Docker CLI command building and injectable
  command runners; shared image/workdir/mount/environment/resource records;
  runtime/profile adapter-owned Docker configuration; mount/workdir/run-dir and
  artifact-root validation; explicit environment handoff and redaction; cheap
  image/runtime provenance; Docker process/failure/log/exit-code integration;
  Docker preflight; fake-command default validation; examples for stage and
  pipeline Docker workflows.
- Confirmed behavior: `loom run CONFIG --executor docker` runs normal Loom
  pipelines whose selected stage attempts execute in Docker containers, while
  the Loom controller remains outside Docker. Users inspect Docker failures
  through existing Loom status/log/failure/diagnostics surfaces and can run
  cheap Docker preflight checks.
- Confirmed defaults: Docker is optional and explicit; Docker CLI only; Docker
  config belongs in runtime/profile adapter options; default preflight and
  default tests avoid image pulls, registry/network probes, real Docker daemon
  requirements, and real images; container choices are provenance/executor
  metadata by default, not mandatory semantic fingerprint inputs.
- Confirmed deferrals: whole-controller-in-container mode, image builds,
  registry auth, automatic pulls, Compose, Kubernetes, Apptainer/Singularity,
  SLURM-container composition, advanced GPU mapping, secret-management
  lifecycle, broad retry/event policy, and cleanup/retention.

Design-agreement follow-up:

- Design agreement resumed from the checkpoint on 2026-05-16.
- Proposed implementation shape and design-agreement queue have been drafted.
- Clear repo-supported decisions are recorded without asking the user.
- The user accepted DAQ-2 on 2026-05-16: Stage 17 should expose a shared
  `container` adapter namespace for generic image/workdir/mount/environment
  fields, with an optional `docker` namespace for Docker-specific flags.
- DAQ-1 through DAQ-12 are resolved and design-safety reviewed.

Examples and validation strategy readback:

- Stage 17 examples are explicit deliverables, not optional tutorial polish.
- Examples should cover direct/prepared stage execution through Docker, normal
  `loom run --executor docker` pipeline execution, Docker preflight, and
  inspectable Docker failure behavior.
- Default examples and tests remain daemon-free through fake Docker command
  runners. Real Docker acceptance is optional, skipped by default, and must not
  be required by `make validate-pr`.
- Validation must prove the real executor command/result contracts, including
  path-parity mounts, redaction, worker-result handoff, failure mapping,
  preflight check IDs, and no raw adapter/environment payload persistence.

Phase-shaping readback:

- Phase shaping is split into five reviewable PR-sized slices: shared
  container contracts, Docker command construction, Docker executor
  integration, preflight/diagnostics, and examples/acceptance hardening.
- The sequence keeps public config and import boundaries before command and
  executor behavior, then adds diagnostics and examples after the execution
  path exists.
- The phase sketch carries suite-level validation obligations and records
  future-compatibility risks for each slice.

Implementation-readiness readback:

- Roadmap-to-requirement, requirement-to-design, design-safety, future-roadmap,
  example-to-validation, phase-shaping, and unresolved-decision checks now
  pass.
- No blocked or `needs discussion` decisions remain in the planning artifact.
- Implementation-plan drafting may start only after the user explicitly
  confirms they are happy with this planning artifact.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Stage 17 planning artifact created from roadmap evidence; Docker is the selected runtime; Apptainer/SLURM-container composition is successor work; user confirmed local/CI per-stage Docker executor parity as the priority. | Per-stage Docker execution, Docker CLI, fake-command tests, no Docker SDK, no default image pulls. | None. | Intent discovery. |
| Intent discovery | Target users, broad user-visible outcome, success examples, hard non-goals, and operational constraints are confirmed. | Normal Docker run, failure inspection, preflight, Docker CLI only, explicit mounts/env, redaction, fake-command default tests. | None. | Capability triage. |
| Capability triage and candidate functional requirements | Capability sort confirmed; FR-1 through FR-9 confirmed as candidate requirements; FR-10 added for Docker stage/pipeline examples. | Include Docker CLI command builder/executor, shared container config, explicit mounts/env, provenance, preflight, fake tests, and examples; keep real Docker opt-in only. | None for triage. | Functionality-agreement review. |
| Functionality agreement review | FRQ-1 through FRQ-5 confirmed; FR-1 through FR-10 accepted. | Per-stage Docker execution only; pipeline examples are normal Loom pipeline runs whose stages use Docker; config is runtime/profile adapter-owned; no default pulls/registry/network-heavy probes. | None. | Functionality and behavior confirmation. |
| Functionality and behavior confirmation | Behavior baseline confirmed. | Include Docker run, stage/pipeline examples, cheap preflight, inspectable failures, redacted provenance, fake-command default tests. | None. | Context compaction/reset checkpoint. |
| Context compaction/reset checkpoint | Complete checkpoint recorded; design pass resumed from this artifact. | Reload planning artifact, workflow, design-agreement prompt, design-safety prompt, and relevant source/docs before asking design questions. | None for functionality; design agreement and design-safety review are now complete. | Design agreement review. |
| Design agreement review | Proposed implementation shape drafted; DAQ-1 through DAQ-12 confirmed. | Reuse prepared worker path; add shared container records and Docker executor under executor ownership; shared `container` adapter namespace plus optional `docker`; path parity for run/artifact mounts; explicit env; fakeable command runner; cheap preflight. | None. | Design-safety review. |
| Design safety review | Completed; DAQ-1 through DAQ-12 upheld with recorded recommendations and no blockers. | Keep shared `container` records small, path-parity mounts fail closed, Docker preflight remains cheap by default, CPU/memory mapping is capability-bounded, raw env values and adapter payloads are not persisted, and fake-command tests must verify command/result contracts. | None after this pass. | Examples and validation strategy. |
| Examples and validation strategy | Examples cover direct/prepared stage Docker execution, normal pipeline Docker execution, Docker preflight, inspectable failures, and optional real Docker acceptance notes. | Daemon-free fake-command examples/tests are default; real Docker is opt-in and skipped outside default validation. | None. | Phase shaping. |
| Phase shaping | Five PR-sized slices are sketched: shared container contracts, Docker command construction, Docker executor integration, preflight/diagnostics, and examples/acceptance hardening. | Public config/import boundaries first, executor behavior second, diagnostics and examples after the execution path exists. | None. | Implementation readiness. |
| Implementation readiness | Readiness checks pass; no blocked or `needs discussion` decisions remain. | Planning artifact is ready for final user confirmation before implementation-plan drafting. | None. | Handoff. |
| Handoff | Design-safety result, examples, validation strategy, phase sketch, accepted risks, and revisit triggers are ready to carry into the implementation-plan draft. | Final confirmation received on 2026-05-16; draft the implementation plan from this artifact. | None. | Implementation-plan drafting. |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Docker CLI command construction | include | Roadmap names Docker command builder using the CLI and rejects Docker SDK dependency. | Candidate requirement FR-2. |
| Per-stage Docker executor over stage-worker | include | Feature docs say per-stage aligns with existing executor contracts; user agreed with local/subprocess parity. | Candidate requirement FR-1. |
| Shared container config records | include | Roadmap names shared image/workdir/mount/environment/resource models and Stage 18 reuse needs them. | Candidate requirement FR-3; design pass must avoid over-generalization. |
| Mount/workdir/run-dir/artifact-root validation | include | Roadmap explicitly names validation and artifact-root mount checks. | Candidate requirement FR-4. |
| Environment allowlist/filtering and redaction | include | User confirmed explicit env handoff and redacted metadata. | Candidate requirement FR-5. |
| Docker runtime/image provenance | include | Roadmap names Docker version and digest when cheaply available. | Candidate requirement FR-6; pulls/registry lookups remain out of default paths. |
| Docker failure/log/exit-code integration | include | Exit criteria require inspectable failures and same run-store semantics. | Candidate requirement FR-7. |
| Docker preflight | include | User confirmed preflight as a success example. | Candidate requirement FR-8; no default pulls or registry contacts. |
| Fake-command tests | include | Roadmap and user-confirmed constraints require default validation without a Docker daemon. | Candidate requirement FR-9. |
| Real Docker integration tests | maybe | Feature docs allow optional real-runtime tests skipped by default; user agreed optional real Docker suite can exist. | Keep optional unless phase planning needs acceptance coverage. |
| Docker stage and pipeline examples | include | User explicitly requested examples of running stages or pipelines in Docker environments. | Candidate requirement FR-10; examples should demonstrate per-stage Docker execution and a full Loom pipeline using the Docker executor. |
| Image build, Compose, Kubernetes, registry auth, automatic pulls, image lock files | defer / out of scope | Roadmap explicitly defers these and user confirmed them as hard non-goals. | Record as explicit deferrals in behavior baseline. |
| Apptainer/Singularity and SLURM-container composition | defer | Roadmap assigns these to Stage 18; user confirmed Stage 18-compatible records without early implementation. | Stage 17 should preserve reusable shape only. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Confirm Stage 17 optimization priority and target user workflow. | Roadmap framing | 1 | Optimize for a reliable per-stage Docker executor for local/CI reproducibility, not broad container orchestration. | Determines whether whole-pipeline containerization, build/pull conveniences, or per-stage executor parity drives scope. | User intent was required before capability triage. | confirmed |
| FRQ-2 | Confirm whether per-stage Docker execution through the existing worker path is the only required execution mode, including for pipeline examples. | FRQ-1 | 2 | Include per-stage Docker execution; examples may show a full Loom pipeline whose stage attempts run in Docker; defer whole-pipeline controller-in-container mode. | Locks the central behavior and prevents duplicate runner/control-plane design. | User requested examples of running stages or pipelines in Docker environments, so the intended meaning of pipeline examples should be explicit. | confirmed |
| FRQ-3 | Confirm Docker option/config ownership and minimum config surface at the requirement level. | FRQ-2 | 3 | Include image, workdir, mounts, environment allowlist, and basic resource mapping as runtime/profile adapter options, not semantic stage spec fields. | Affects user-authored configuration and future portability across executors. | Resolved directly from confirmed portability goal, `docs/features/runtime-resources.md`, and existing runtime/profile ownership. | confirmed |
| FRQ-4 | Confirm default external side effects. | FRQ-2 | 4 | No automatic image pulls, registry auth, or network/daemon-heavy probes in default preflight; runtime may fail if Docker cannot run the selected image. | Defines default safety and offline/test behavior. | Resolved directly from user-confirmed constraints and roadmap deferrals. | confirmed |
| FRQ-5 | Confirm examples and demonstrations as explicit Stage 17 functionality. | FRQ-2 | 5 | Include docs/tests/examples for direct/prepared stage Docker execution, normal `loom run --executor docker` pipeline execution, preflight, and inspectable failures; keep examples daemon-free by default with optional real Docker notes. | Examples are now part of the requested product outcome and need validation traceability. | Confirmed by user request and FRQ-2 answer. | confirmed |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Per-stage Docker execution | none | Run one prepared stage attempt inside Docker by invoking the existing durable stage-worker command in the container. | Provides executor parity without duplicating runner logic. | Include Docker execution for selected stages during `loom run`; defer whole-pipeline container controller mode. | `loom run CONFIG --executor docker` executes stages through Docker and reports normal run results. | Parent execution prepares/finalizes attempts; Docker executor launches the containerized worker and reads the standard worker result. | Local/CI containerized stage execution. | Fake command integration test plus small local pipeline fixture with injected Docker runner. | confirmed |
| FR-2 | Docker CLI command builder and runner | FR-1 | Build deterministic `docker run` commands from validated container options and run them through an injectable command runner. | Keeps Docker behavior inspectable, testable, and dependency-light. | Include command construction, process capture, redacted command projection, and fake runner support; no Docker SDK. | Users can diagnose the command Loom attempted without secrets. | Command builder owns argument ordering and redaction; executor owns process result interpretation. | Reviewable Docker invocation. | Unit tests for command argv, quoting-free argument lists, redaction, and process result mapping. | confirmed |
| FR-3 | Shared container configuration records | FR-1 | Provide strict records for image, workdir, mounts, environment handoff, and resource mapping policy. | Stage 17 needs Docker config and Stage 18 needs reusable container concepts. | Include shared generic records plus Docker-specific options where needed; defer Apptainer-specific fields. | Users configure image, workdir, mounts, and env in runtime/profile options. | Runtime parsing validates plain-data records and feeds Docker command construction. | Stable config surface. | Contract tests for records, serialization, invalid fields, and Stage 18-neutral naming. | confirmed |
| FR-4 | Mount, workdir, run-dir, and artifact-root validation | FR-1 | Validate explicit host source paths, absolute container targets, modes, workdir shape, run-dir writability, and local artifact-root visibility. | Bad mounts are the main way Docker execution can diverge from local/subprocess semantics. | Include local path validation and explicit failure diagnostics; defer broad remote-store mount automation. | Preflight and runtime failures identify the bad mount or writable path. | Docker executor/preflight checks reject unsafe or incomplete mount plans before or during execution. | Reliable filesystem handoff. | Unit and preflight tests for missing sources, relative targets, read-only run dirs, and artifact-root gaps. | confirmed |
| FR-5 | Explicit environment handoff and redaction | FR-1 | Pass only selected environment variables and persist keys/redacted values only. | Prevents accidental secret leakage in commands, logs, and metadata. | Include allowlist/explicit-env behavior and redacted metadata; defer secret management. | Users can request env vars without Loom recording secret values. | Docker command uses env values at runtime but executor metadata stores redacted summaries. | Safe environment handoff. | Unit tests for allowlist, missing required env diagnostics, and redacted command metadata. | confirmed |
| FR-6 | Docker image/runtime provenance | FR-1 | Record image reference, Docker runtime/version when cheap, and image digest when cheaply available without pulling by default. | Container identity is core provenance, but registry access must remain explicit. | Include cheap local metadata; defer image lock files and automatic pulls. | Inspectable run metadata shows selected image/runtime facts. | Executor metadata nests Docker provenance under executor-specific metadata. | Reproducibility evidence. | Fake command tests for version/digest success, unavailable digest, and redacted details. | confirmed |
| FR-7 | Docker failure, log, exit-code, and timeout metadata integration | FR-1 | Map Docker process failures and worker-result conflicts into existing execution failure/result semantics with log paths. | Exit criteria require inspectable Docker failures. | Include exit-code/container-start/stage-command failure distinctions where available; defer shared retry/timeout policy to Stage 19. | Users inspect failures through normal Loom diagnostics. | Docker executor returns `StageExecutionResult` with structured failure and executor metadata. | Debuggable Docker failures. | Unit/integration tests for nonzero Docker exit, missing worker result, failed worker result, and log capture. | confirmed |
| FR-8 | Docker preflight | FR-3 | Add preflight checks for Docker command availability, image reference, mount sources, run/artifact writability, required env vars, and resource support. | Users need actionable feedback before launching containers. | Include cheap checks by default; defer pulls, registry auth, and network probes. | `loom preflight` reports Docker readiness for selected executor. | Diagnostics expose stable check IDs and structured details. | Safe dry diagnostics. | Contract/integration tests for preflight check IDs and pass/fail cases. | confirmed |
| FR-9 | Default fake-command validation and optional real-Docker acceptance | FR-1 | Prove core behavior with fake commands by default; optionally provide skipped real Docker tests if useful. | Keeps CI deterministic while allowing maintainer smoke coverage. | Include fake-command unit/contract/integration coverage; real Docker suite remains optional. | Contributors can run default checks without Docker. | Test utilities inject command runners and avoid daemon/network dependencies. | Reviewable validation. | `make validate-pr` stays Docker-free; optional marker or env-gated tests may cover real Docker. | confirmed |
| FR-10 | Docker stage and pipeline examples | FR-1 | Provide examples and docs/tests showing direct or prepared stage execution in Docker and a normal Loom pipeline whose stage attempts run through Docker executor environments. | The user wants Stage 17 to demonstrate how stages and pipelines run in Docker. | Include examples for Docker stage execution, full pipeline execution through the Docker executor, preflight, and inspectable failure; defer whole-pipeline controller-in-container mode. | Users can copy or inspect examples for running stages or pipelines in Docker environments. | Examples exercise the same Docker executor and fake-command/default validation paths rather than special demo-only code. | Learnable Docker workflows. | Documentation/example tests with fake Docker command runner by default; optional real Docker notes or acceptance test if selected later. | confirmed |

## Behavior Baseline

Included functionality:

- Per-stage Docker execution for selected stage attempts during normal Loom
  runs.
- Docker CLI command building and injectable fake/real command runner support.
- Shared container configuration records for image, workdir, mounts,
  environment handoff, and resource mapping policy.
- Runtime/profile adapter-owned Docker configuration, not semantic stage-spec
  Docker fields.
- Mount, workdir, run-directory, and local artifact-root validation.
- Explicit environment handoff with redacted persisted metadata.
- Docker image/runtime provenance, including cheap Docker version and image
  digest facts when available without pulling.
- Docker process, worker-result, failure, log, exit-code, and timeout-metadata
  integration through existing execution result semantics.
- Docker preflight with stable checks for cheap local readiness.
- Fake-command default validation and optional real Docker acceptance coverage.
- Examples for direct/prepared stage Docker execution, normal
  `loom run --executor docker` pipeline execution, Docker preflight, and
  inspectable failures.

User-visible behavior:

- Users can run `loom run CONFIG --executor docker` and receive normal Loom run
  output while selected stages execute through Docker containers.
- Users can inspect Docker failures through the same status, log, failure, and
  diagnostics surfaces used by local/subprocess execution.
- Users can run preflight for a Docker-selected run and see actionable Docker
  command, image config, mount, environment, artifact-root, and resource
  diagnostics.
- Users can read examples showing both a Docker stage workflow and a full Loom
  pipeline whose stage attempts run in Docker environments.

Default behavior:

- Docker is optional and selected explicitly.
- Docker execution uses the Docker CLI, not the Docker Python SDK.
- Docker configuration is supplied through runtime/profile adapter options.
- The controller remains outside Docker; stage attempts run inside Docker.
- No automatic image pull, registry authentication, Docker Compose, Kubernetes,
  Apptainer/Singularity, or whole-controller-in-container behavior is included.
- Default preflight remains cheap and does not perform registry/network probes
  or image pulls.
- Default tests and examples are daemon-free through fake command runners,
  with any real Docker acceptance path opt-in.
- Container choices are recorded as provenance/executor metadata by default,
  not semantic fingerprint inputs.

Failure behavior and diagnostics:

- Missing Docker command, missing image config, invalid mounts, non-absolute
  container targets, read-only run directories, missing artifact-root mounts,
  missing required environment variables, unsupported resource mappings, Docker
  process failures, missing worker results, and worker-result conflicts produce
  structured failures or preflight diagnostics.
- Persisted command and environment metadata must be redacted and must not
  store secret values.
- Runtime may fail if Docker cannot run the selected image; Stage 17 does not
  hide that by pulling images or authenticating registries automatically.

Explicit deferrals:

- Whole-pipeline controller-in-container mode.
- Image build commands and image lock files.
- Registry authentication helpers and automatic image pulls.
- Docker Compose, Kubernetes, and cloud container orchestration.
- Apptainer/Singularity and SLURM-container composition.
- Advanced GPU mapping.
- Secret-management lifecycle.
- Shared retry/failure-category/transaction policy beyond Stage 17 executor
  metadata; Stage 19 owns broader reliability policy.
- Runtime event and event-sink policy; Stage 20 owns committed runtime events
  and observe-only sinks.
- Cleanup/retention behavior for derived container artifacts beyond preserving
  useful records; Stage 21 owns cleanup and retention.

Out-of-scope behavior:

- Treating containers as a security sandbox for untrusted code.
- Replacing the stage-worker contract or duplicating runner lifecycle inside
  the Docker executor.
- Requiring Docker, a running Docker daemon, network access, or real images for
  default package tests or `make validate-pr`.
- Making Docker runtime choices mandatory semantic fingerprint inputs.

Context compaction/reset checkpoint:

- Checkpoint status: completed on 2026-05-16 after behavior confirmation
- Notes path: `docs/roadmap/stage-17/planning.md`
- Resume instruction: resume with `.codex/workflows/roadmap-stage-planning.md`
  and continue Stage 17 design agreement from
  `docs/roadmap/stage-17/planning.md`. Treat roadmap framing, intent
  discovery, capability triage, functionality agreement, and behavior baseline
  as confirmed. Reload `.codex/prompts/roadmap-stage-design-agreement.md`,
  `.codex/prompts/roadmap-stage-design-safety-review.md`, `docs/structure.md`,
  `docs/features/container-executors.md`, `docs/features/execution.md`,
  `docs/features/runtime-resources.md`, `docs/features/preflight.md`,
  `docs/features/provenance.md`, `docs/features/reliability.md`,
  `docs/features/testing.md`, and current executor/runtime/preflight source
  before drafting the proposed implementation shape and design-agreement queue.
- Functionality and behavior reopened after checkpoint: not applicable

## Proposed Implementation Shape

Likely modules or packages:

- `loom.pipeline.executors.containers` for shared container value records and
  validation helpers that are not Docker-specific: image reference, workdir,
  mount, environment handoff summary, resource mapping policy, path safety,
  command redaction helpers, and shared command-result projection.
- `loom.pipeline.executors.docker` for Docker-specific options, command
  builder, command runner protocol, process result mapping, provenance helpers,
  preflight-facing summaries, and `DockerExecutor`.
- `loom.pipeline.runtime.capabilities` for the built-in Docker executor
  descriptor and resource capability declarations.
- `loom.diagnostics.models` and `loom.diagnostics.preflight` for stable Docker
  check IDs and cheap selected-executor checks.
- `loom.cli.run` for executor resolution and thin CLI wiring to
  `DockerExecutor`.
- Tests under `tests/unit/loom/pipeline/executors/`, `tests/contracts/`, and
  integration/e2e examples with injected/fake Docker command runners.

Likely public classes, functions, or protocols:

- Shared records such as `ContainerMount`, `ContainerRuntimeOptions`,
  `ContainerEnvironment`, and redacted command/metadata projection helpers.
- Docker records such as `DockerOptions`, `DockerCommand`, and
  `DockerCommandResult`, plus a fakeable `DockerCommandRunner` protocol and
  default subprocess-backed runner.
- `DockerExecutor`, exported lazily from `loom.pipeline.executors` like
  `SubprocessExecutor`.
- Preflight check IDs such as `executor.docker.command`,
  `executor.docker.image`, `filesystem.docker.mounts`,
  `filesystem.docker.run_writable`, `filesystem.docker.artifact_root`,
  `runtime.docker.options`, and `resources.docker.mapping`.

Likely internal helpers:

- Docker argv builder with deterministic argument ordering and no shell string
  interpolation.
- Mount validation helpers that reject missing host sources, non-absolute
  container targets, unsupported modes, unsafe targets, read-only run dirs, and
  missing local artifact-root visibility.
- Environment handoff builder that passes only explicit variables or selected
  required host names and records redacted summaries.
- Docker metadata collectors for cheap `docker --version` and optional local
  image digest inspection without pulling.
- Worker command builder that reuses the current `loom stage run --run-uri ...
  --stage ... --attempt ... --format json` invocation inside `docker run`.
- Process/worker-result conflict normalizer aligned with `SubprocessExecutor`.

Data flow:

- CLI/config/runtime merges resolve `RunOptions` and selected runtime/profile
  adapter options.
- `loom.cli.run` builds a `DockerExecutor` when the selected executor is
  `docker` and passes the authority-backed run store into the normal
  `PipelineRunner`.
- `PipelineRunner` sees `DockerExecutor.requires_prepared_worker_request` and
  prepares one durable worker request per runnable stage attempt.
- `DockerExecutor` validates/normalizes Docker options for that request,
  builds a `docker run` argv with path-parity mounts, launches the command
  through an injectable runner, reads the standard worker result, and returns a
  `StageExecutionResult`.
- Parent execution validates outputs, commits stage result state, updates
  artifact indexes, records failures/log paths, and finalizes run status.

Dependency direction:

- `loom.pipeline.executors.docker` may import execution models, runtime option
  records, serialization primitives, timestamps, and run-store path helpers
  already required by prepared workers.
- Shared container models must remain import-light and must not import Docker,
  CLI, diagnostics, plugin discovery, run catalog, or optional SDK code.
- Diagnostics consumes executor/runtime summaries and stable check IDs; Docker
  executor code must not import CLI presentation.
- CLI selects and instantiates executors but must not implement Docker command
  construction or parse Docker output.

Extension points and flexibility boundaries:

- Shared container records should be generic enough for Stage 18
  Apptainer/Singularity mount, workdir, environment, provenance, and command
  redaction reuse.
- Docker-specific behavior stays in Docker options and command builders so
  Stage 18 can add Apptainer-specific bind/GPU/scheduler behavior without
  changing Docker contracts.
- Optional real Docker tests remain opt-in; default test surfaces use command
  runner injection.
- The stage does not introduce plugin loading for executors, but it should not
  block future executor plugin registration through existing descriptor
  patterns.

Generic interface, adapter, or protocol shape:

- Shared container value records are plain-data serializable and runtime-option
  friendly.
- Docker command execution uses a narrow `DockerCommandRunner` protocol,
  analogous to SLURM command runners, with a subprocess-backed default and fake
  test implementation.
- Executor descriptors claim Docker-relevant adapter namespaces and resource
  capabilities without importing concrete Docker execution at runtime
  validation time.

Future-roadmap impact:

- Stage 18 can reuse the shared container records, redaction rules, path-safety
  helpers, provenance conventions, and fake-command testing pattern for
  Apptainer/Singularity and SLURM-container composition.
- Stage 19 can wrap Docker command results and executor metadata with shared
  retry, timeout, failure-category, transaction, status-detail, and
  retry-safety policy without changing Stage 17 result shapes.
- Stage 20 can project committed Docker/container facts into runtime events and
  observe-only event sinks.
- Stage 21 can use preserved log/staging/materialization facts for cleanup
  policy without treating container staging as authority truth.

Compatibility constraints:

- Existing local, subprocess, and SLURM behavior must not change.
- `loom run` with `local`, `subprocess`, or SLURM executors must preserve
  existing CLI output and validation.
- Existing runtime option parsing and profile merge semantics should be
  extended through adapter namespaces, not by adding Docker fields to semantic
  stage specs.
- Default imports, help text, preflight, and tests must not require Docker,
  network access, real images, or the Docker Python SDK.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Package and ownership shape for shared container and Docker-specific code. | FR-1, FR-2, FR-3 | 1 | recorded recommendation | Put shared container records/helpers in `loom.pipeline.executors.containers`; put Docker-specific command/executor behavior in `loom.pipeline.executors.docker`. | Prevents Docker logic from leaking into runner/runtime/diagnostics and preserves Stage 18 reuse. | Repo boundaries give a clear recommendation; no user input needed unless rejected by design-safety review. | confirmed |
| DAQ-2 | Public runtime/profile config namespace for shared container and Docker-specific options. | DAQ-1, FR-3, FR-10 | 2 | recorded recommendation | Use a shared `container` adapter namespace for image/workdir/mount/env fields, with optional `docker` namespace for Docker-specific flags. Reject keeping all Stage 17 authored config under `docker`. | This is durable public config surface and affects Stage 18 migration/reuse. | User accepted the recommended shared namespace approach; design-safety review upheld it with a narrow generic-schema boundary. | confirmed |
| DAQ-3 | Executor lifecycle integration. | FR-1 | 3 | recorded recommendation | `DockerExecutor` should set `requires_prepared_worker_request = True` and reuse the parent-prepared durable worker path. | Avoids a second runner and preserves existing finalization semantics. | Current runner/source behavior gives a clear recommendation. | confirmed |
| DAQ-4 | Run/artifact path semantics inside containers. | FR-1, FR-4 | 4 | recorded recommendation | Stage 17 should require path-parity mounts for run directories and local artifact roots: the container path must match the persisted local path used by run-store metadata. Explicit path rewriting is deferred. | Prevents worker/run-store path drift and avoids inventing container path translation for persisted records. | Current worker/run-store behavior and feature docs support this; no user input needed unless design-safety overturns it. | confirmed |
| DAQ-5 | Environment handoff and redaction design. | FR-5 | 5 | recorded recommendation | Docker should pass only explicit runtime/container environment entries or selected required host names, and persist key summaries/redacted values only. Full host env forwarding remains unsupported by default. | Prevents secret leakage while still supporting required env workflows. | Confirmed behavior and feature docs provide a clear recommendation. | confirmed |
| DAQ-6 | Docker command-runner and result protocol. | FR-2, FR-7, FR-9 | 6 | auto-approved | Add a narrow fakeable command-runner protocol and bounded command-result record, following the SLURM runner precedent. | Enables deterministic default tests and inspectable executor metadata. | Design-safety review upheld this as local, traceable, low-risk, and directly validated by fake-command tests. | confirmed |
| DAQ-7 | Docker resource capability mapping. | FR-3, FR-8 | 7 | recorded recommendation | Declare basic CPU and memory mapping support for Docker; treat GPU mapping as unsupported in Stage 17 unless a future phase adds a narrow explicit GPU policy. | Keeps resource behavior useful without prematurely designing advanced GPU access. | Roadmap defers advanced GPU mapping and runtime descriptors already encode support levels. | confirmed |
| DAQ-8 | Provenance and fingerprint policy. | FR-6 | 8 | recorded recommendation | Record image/runtime/container facts in executor metadata/provenance, but do not make Docker choices mandatory semantic fingerprint inputs in Stage 17. | Preserves reproducibility evidence without changing resume semantics. | Confirmed behavior and runtime-resources guidance give a clear recommendation. | confirmed |
| DAQ-9 | Preflight behavior and check IDs. | FR-8 | 9 | auto-approved | Add Docker-specific runtime/executor/filesystem/resource checks that are cheap by default and skip expensive pull/registry/daemon-heavy probes. | Gives users actionable diagnostics without violating no-network defaults. | Design-safety review upheld this as a straightforward extension of existing selected-executor checks, provided daemon-heavy image probes remain opt-in. | confirmed |
| DAQ-10 | CLI/public API surface. | FR-1, FR-2, FR-10 | 10 | recorded recommendation | Extend existing `loom run --executor docker` and preflight paths; lazily export `DockerExecutor`; do not add a Docker-specific CLI command group in Stage 17. | Keeps CLI thin and avoids broad command surface. | Existing CLI/executor patterns give a clear recommendation. | confirmed |
| DAQ-11 | Timeout/reliability scope. | FR-7 | 11 | recorded recommendation | Record available timeout/process metadata from Docker command results, but defer shared timeout enforcement/retry/failure-category policy to Stage 19. | Avoids creating a second reliability policy inside Docker. | Roadmap and reliability docs give a clear recommendation. | confirmed |
| DAQ-12 | Examples and validation surface. | FR-9, FR-10 | 12 | recorded recommendation | Add daemon-free examples/tests using fake Docker command runners by default, plus optional real Docker acceptance notes or tests gated outside `make validate-pr`. | Satisfies examples requirement while preserving deterministic validation. | Confirmed behavior and testing docs give a clear recommendation. | confirmed |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Future-roadmap impact | Interface, adapter, or protocol impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Package and ownership shape for shared container and Docker code | Shared container records/helpers in `loom.pipeline.executors.containers`; Docker-specific command/executor behavior in `loom.pipeline.executors.docker`. | Not surfaced; repo-supported recommendation. | Putting Docker config in runtime, diagnostics, CLI, or stores; putting shared records inside a Docker-only module. | Matches executor ownership and keeps shared records available for Stage 18. | Clear ownership boundaries reduce cross-module coupling. | Stage 18 can reuse container records without importing Docker behavior. | Enables Apptainer/Singularity reuse. | Shared records become reusable executor-adapter value objects. | Import-boundary tests and package API tests. | Revisit if shared records begin importing Docker/runtime side effects or Stage 18 cannot reuse them. | confirmed |
| DAQ-2 | Public runtime/profile config namespace | Shared `container` adapter namespace for generic image/workdir/mount/env, with optional `docker` namespace for Docker-specific flags. | User agreed on 2026-05-16; design-safety review upheld the split. | Docker-only namespace for all authored Stage 17 config; semantic stage-spec fields. | Public config namespace affects user examples and Stage 18 reuse. | Generic namespace reduces later migration and avoids duplicating generic container fields. | Creates public generic container surface in Stage 17, but keeps Docker-specific flags separate and bounded. | Direct Stage 18 impact: Apptainer/Singularity can consume the generic `container` namespace without Docker migration. | Executor descriptors should claim `container` and `docker` namespaces; public records should distinguish generic and Docker-specific fields. The generic namespace must stay limited to image/workdir/mount/env/resource intent and must not become a universal orchestration API or persist raw adapter payloads. | Config/profile merge tests and docs examples for run-level and per-stage adapter options. | Revisit if Stage 18 needs incompatible generic fields, if schema evolution needs namespacing beyond plain adapter payloads, or if Docker-specific flags leak into `container`. | confirmed |
| DAQ-3 | Executor lifecycle integration | `DockerExecutor.requires_prepared_worker_request = True`; reuse prepared worker path. | Not surfaced; repo-supported recommendation. | Directly running stage objects in Docker executor; new runner mode; whole-controller-in-container mode. | Current runner already supports prepared worker executors and Docker behavior needs subprocess-like semantics. | Avoids duplicating runner lifecycle. | Future container runtimes can follow the same prepared-worker pattern. | Aligns Stage 18 and later submitted container behavior. | Reuses existing `Executor` protocol and worker request/result contracts. | Integration tests for prepared worker request and parent-owned finalization. | Revisit only if path-parity constraints make worker reconstruction impossible. | confirmed |
| DAQ-4 | Run/artifact path semantics inside containers | Require path-parity mounts for run dirs and local artifact roots in Stage 17. | Not surfaced; repo-supported recommendation; design-safety review upheld with fail-closed semantics. | Host/container path rewriting; implicit artifact materialization into alternate container paths; broad remote-store mount automation. | Current worker resolves file run URIs and local store paths directly; parity avoids stale path metadata. | Simplifies correctness and failure diagnosis, but implementation must fail closed when a selected run URI or artifact root has no host-visible path that can be mounted at the same path. | Stage 18 can add explicit mapping only if needed. | Supports reliable Docker now while leaving path rewriting for later. | Container mount records encode source/target/mode and validation; no path-translation protocol is introduced in Stage 17. | Mount validation/preflight tests for parity, missing host paths, read-only run dirs, non-file or non-local store limitations, and artifact-root presence. | Revisit when Stage 18, remote stores, or non-local authority backends require explicit host/container path translation. | confirmed |
| DAQ-5 | Environment handoff and redaction | Pass explicit variables/selected host names only; persist keys/redacted values only. | Not surfaced; confirmed behavior; design-safety review upheld with a strict persistence boundary. | Forwarding full host environment; persisting raw env values; adding secret manager. | Prevents leaks while supporting required Docker env. | Keeps metadata shareable if redaction happens before command, failure, provenance, and diagnostic records are written. | Future secret-management can add explicit mechanisms without breaking redaction. | Stage 18 can reuse the same environment handoff. | Shared container environment record and redaction helper; runtime metadata still records only safe counts/namespaces, while executor metadata may record explicit selected key names and redacted values only. | Unit tests for allowlist, missing required env, secret-looking keys/values, command redaction, failure metadata redaction, and no raw adapter/env payload persistence. | Revisit when a secret-management stage exists or if maintainers decide environment key names themselves need stronger redaction. | confirmed |
| DAQ-6 | Docker command-runner and result protocol | Add fakeable runner protocol and bounded result record. | Not surfaced; design-safety review upheld auto-approval. | Calling subprocess directly throughout executor; shell command strings; unbounded stdout/stderr persistence. | SLURM precedent supports this and fake tests require it. | Centralizes command execution behavior without changing the executor protocol. | Other container runtimes can copy the pattern. | Stage 18 command runners can align without inheriting Docker-specific argv fields. | Narrow protocol, not universal executor framework. It should expose argv, return code, bounded stdout/stderr, timing/error facts, and redacted projection only. | Unit tests with fake runner, bounded output, deterministic argv, and process/worker conflict mapping. | Revisit if multiple runtime command runners need a shared operation primitive. | confirmed |
| DAQ-7 | Docker resource capability mapping | Basic CPU/memory support; GPU unsupported in Stage 17. | Not surfaced; repo-supported recommendation; design-safety review upheld with capability precision. | Advanced GPU mapping; ignoring all resources; claiming full GPU support. | Roadmap defers advanced GPU mapping; cpu/memory are common Docker flags. | Avoids overpromising if descriptors distinguish mapping support from exact enforcement guarantees. | GPU policy can be added later without changing CPU/memory semantics. | Stage 18 can model GPU through Apptainer/SLURM separately. | Executor descriptor capability records should mark CPU/memory as Docker-mappable with the appropriate enforcement expectation and GPU as unsupported/error for Stage 17. | Capability, preflight, command-builder, unsupported GPU, and descriptor tests. | Revisit when advanced GPU mapping is planned or when Docker CPU/memory semantics need a more precise cross-platform policy. | confirmed |
| DAQ-8 | Provenance and fingerprint policy | Record Docker facts in executor metadata/provenance; do not make them mandatory semantic fingerprint inputs. | Not surfaced; repo-supported recommendation; design-safety review upheld. | Folding image digest into fingerprints by default; omitting container provenance. | Runtime-resources docs say operational choices are provenance by default. | Preserves existing resume behavior. | Semantic policy can be introduced later explicitly. | Stage 19/20/21 can consume metadata without changing fingerprints. | Executor metadata/provenance fields only; digest lookup is best-effort and must not pull images or require registry access in default paths. | Provenance projection tests for present digest, missing digest, unavailable Docker command, and no fingerprint change. | Revisit if a future stage defines image-as-semantic-input policy or image lock files. | confirmed |
| DAQ-9 | Preflight behavior and check IDs | Cheap Docker selected-executor checks with stable IDs; no default pulls/registry probes. | Not surfaced; design-safety review upheld auto-approval. | Pulling images by default; registry auth probes; daemon-required image inspection by default; no Docker preflight. | Matches confirmed behavior and preflight docs. | Keeps diagnostics deterministic. | Expensive probes can be added opt-in later. | Useful for Stage 18 compatibility if Apptainer can follow the same selected-executor check pattern. | Diagnostics consumes Docker summaries; default checks should cover command availability, option shape, image reference presence, mount/run/artifact path checks, required env availability, and resource mapping without contacting registries. | Contract tests for stable check IDs, selected-executor behavior, cheap default behavior, skipped expensive probes, and JSON output. | Revisit when opt-in expensive probes are designed. | confirmed |
| DAQ-10 | CLI/public API surface | Extend `loom run --executor docker`, preflight, and lazy Python exports; no Docker command group. | Not surfaced; repo-supported recommendation. | New Docker CLI group; CLI-owned command construction; eager Docker imports. | CLI should stay thin and existing executor selection is the natural surface. | Limits user-facing churn. | Future executor plugins can reuse thin selection pattern. | Stage 18 can add executor names without CLI redesign. | Public `DockerExecutor` and config records are import-light. | CLI contract tests and package import tests. | Revisit if Docker-specific operations beyond execution are added. | confirmed |
| DAQ-11 | Timeout/reliability scope | Record available process/timeout facts, but defer shared policy/enforcement to Stage 19. | Not surfaced; repo-supported recommendation. | Implementing Docker-specific retry/timeout policy; ignoring available process facts. | Reliability docs own shared policy; Stage 17 only needs inspectable executor facts. | Avoids policy duplication. | Stage 19 can wrap existing metadata. | Direct Stage 19 compatibility. | Executor metadata, not new reliability protocol. | Failure metadata tests. | Revisit in Stage 19. | confirmed |
| DAQ-12 | Examples and validation surface | Daemon-free fake-runner examples/tests by default; optional real Docker acceptance outside default validation. | Not surfaced; repo-supported recommendation. | Requiring real Docker for examples or `make validate-pr`; only unit tests with no examples. | Meets user examples request while preserving deterministic CI. | Keeps validation practical. | Optional acceptance can grow later. | Stage 18 can mirror the pattern. | Test helpers for command runners. | Example/docs tests plus optional marked real Docker test. | Revisit if examples cannot prove behavior without real Docker. | confirmed |

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | recorded recommendation | Considered whether shared records in a Docker-only module would be simpler; rejected because Stage 18 reuse is explicit. Design-safety review added the import-light boundary as a validation obligation. | FR-2, FR-3 | record recommendation | confirmed |
| DAQ-2 | recorded recommendation | Generic namespace may be premature public API; Docker-only namespace may force Stage 18 migration or duplication. User accepted the generic namespace with Docker-specific override boundary, and design-safety review upheld it only as a narrow adapter-owned record shape. | FR-3, FR-10 | record recommendation | confirmed |
| DAQ-3 | recorded recommendation | Direct execution would duplicate runner lifecycle; whole-controller mode is explicitly deferred. | FR-1 | record recommendation | confirmed |
| DAQ-4 | recorded recommendation | Path mapping would improve flexibility but requires translating persisted file URIs and run-store paths; design-safety review upheld path parity only with explicit fail-closed diagnostics for non-mountable local paths. | FR-1, FR-4 | record recommendation | confirmed |
| DAQ-5 | recorded recommendation | Full environment inherit is easier but conflicts with confirmed redaction/safety behavior; design-safety review added no-raw-env/adapter-payload persistence obligations. | FR-5 | record recommendation | confirmed |
| DAQ-6 | auto-approved | Checked against SLURM command-runner precedent and fake-test requirements; design-safety review upheld because the protocol is narrow, local, and directly testable. | FR-2, FR-9 | summarize | confirmed |
| DAQ-7 | recorded recommendation | Full GPU support would exceed roadmap; ignoring all resources would underuse existing capability model. Design-safety review requires precise CPU/memory capability language and GPU unsupported errors. | FR-3, FR-8 | record recommendation | confirmed |
| DAQ-8 | recorded recommendation | Including image identity in fingerprints may be valid later but would alter resume semantics now; design-safety review requires best-effort digest metadata without pulls or registry access. | FR-6 | record recommendation | confirmed |
| DAQ-9 | auto-approved | Directly extends existing selected-executor preflight checks; design-safety review upheld only for cheap default checks and stable IDs. | FR-8 | summarize | confirmed |
| DAQ-10 | recorded recommendation | A Docker command group is unnecessary for confirmed behavior and would broaden CLI surface. | FR-1, FR-10 | record recommendation | confirmed |
| DAQ-11 | recorded recommendation | Docker-specific retry/timeout policy would conflict with Stage 19 ownership. | FR-7 | record recommendation | confirmed |
| DAQ-12 | recorded recommendation | Real Docker examples are useful but cannot be default validation. | FR-9, FR-10 | record recommendation | confirmed |

## Design Safety Review

| Finding | Affected decision or requirement | Future-roadmap or compatibility risk | Interface, adapter, or protocol reuse risk | Recommended planning revision | Status |
| --- | --- | --- | --- | --- | --- |
| Shared `container` adapter namespace is justified, but only as a small executor-adapter record shape. It must not become root runtime schema, semantic stage spec, or a generic orchestrator API. | DAQ-1, DAQ-2, FR-3 | Over-broad fields would either force Stage 18 to inherit Docker assumptions or require a later public config migration. | Generic records must cover image reference, workdir, mounts, explicit environment handoff, and resource mapping intent only; Docker flags stay under `docker`. | Reclassify DAQ-2 from resolved `needs discussion` to recorded recommendation; add validation that Docker descriptors claim both `container` and `docker` namespaces and reject/diagnose unclaimed namespaces without persisting raw adapter payloads. | recommendation recorded |
| Path-parity mounts are the correct Stage 17 default, but implementation must fail closed when run directories or local artifact roots are not host-visible at the same path. | DAQ-4, FR-1, FR-4 | Stage 18 or remote-store workflows may need explicit path translation; Stage 17 should not invent that protocol while current worker metadata uses file paths directly. | `ContainerMount` can stay source/target/mode based; no path-rewrite adapter is introduced. | Keep path parity, but record non-local/non-mountable stores and mismatched run/artifact paths as preflight/runtime failures, not implicit remapping. | recommendation recorded |
| Environment handoff and redaction must be enforced before command, failure, provenance, diagnostics, and runtime metadata persistence. | DAQ-5, FR-5 | Secret leakage would make persisted records unsafe and hard to migrate; Stage 18 should reuse the same redaction model. | Shared `ContainerEnvironment` should express explicit values and required host names without authorizing full host environment inheritance. | Add tests and examples that prove raw values and raw adapter payloads are absent from persisted executor metadata and `runtime.json`; persist only selected key summaries/redacted values where needed. | recommendation recorded |
| Docker resource mapping should avoid claiming stronger enforcement than Docker flags provide. | DAQ-7, FR-3, FR-8 | Stage 18 SLURM plus Apptainer may enforce CPU/memory through the scheduler instead of the container runtime; imprecise capability claims would confuse cross-executor diagnostics. | Descriptor records should distinguish support level and enforcement expectation for CPU/memory, and mark GPU unsupported/error in Stage 17. | Keep CPU/memory mapping and GPU deferral, but require descriptor, preflight, and command-builder tests for supported, ignored, and unsupported resource cases. | recommendation recorded |
| Cheap preflight and provenance defaults must not smuggle in daemon-heavy or network behavior. | DAQ-8, DAQ-9, FR-6, FR-8 | Default CI and local validation must stay Docker-free; Stage 18 should be able to mirror cheap checks without depending on runtime daemons. | Docker metadata collectors should be best-effort helpers behind executor/preflight ownership, not provenance-owned Docker imports. | Keep command availability, option, mount, env, and resource checks cheap by default; make image inspection/digest collection nonblocking or opt-in when it requires daemon/registry access. | recommendation recorded |
| The fake-command validation strategy is acceptable only if it tests the real command/result contracts, not isolated helpers. | DAQ-6, DAQ-12, FR-2, FR-7, FR-9, FR-10 | Without contract-level fake runs, Stage 18 could copy unproven command-builder conventions and Docker failures might bypass existing result semantics. | `DockerCommandRunner` can remain Docker-specific; do not generalize a cross-runtime runner until multiple runtimes need one. | Upheld DAQ-6 and DAQ-9 as auto-approved; require fake integration tests that drive `DockerExecutor` through prepared worker request/result handling, redaction, log paths, and process/worker conflict mapping. | auto-approved upheld |
| Store and executor ownership boundaries are sound if Docker only consumes prepared-worker/run-store contracts and never writes artifact indexes or final statuses itself. | DAQ-1, DAQ-3, FR-1, FR-7 | Bypassing parent finalization would conflict with Stage 19 transaction policy and Stage 21 cleanup assumptions. | Docker executor metadata remains nested under execution result/failure records; no new store authority contract is introduced. | Keep lifecycle ownership in `PipelineRunner`; Docker executor returns `StageExecutionResult` and structured failure metadata only. | auto-approved upheld |

Gate result:

- Status: passed
- Reviewer: roadmap-stage design-safety review, 2026-05-16.
- Blockers: none from design-safety review.
- Auto-approved decisions upheld:
  - DAQ-6 command-runner/result protocol.
  - DAQ-9 cheap selected-executor preflight/check-ID extension.
- Auto-approved or candidate decisions overturned:
  - None blocked or reopened.
  - DAQ-2 was reclassified from resolved `needs discussion` to recorded
    recommendation because the user accepted the public namespace and
    design-safety review found a safe narrow boundary.
- Recorded recommendations:
  - Keep `container` adapter records narrow and executor-owned; put
    Docker-only flags in `docker`.
  - Fail closed for non-mountable/non-path-parity run and artifact roots.
  - Redact before persistence across command, failure, provenance, diagnostics,
    and runtime metadata paths.
  - Model Docker CPU/memory support with precise capability/enforcement
    language and keep GPU unsupported in Stage 17.
  - Keep default preflight and provenance collection cheap; no default pulls,
    registry contacts, or daemon-heavy image inspection.
  - Use fake-command tests at executor integration boundaries, not only command
    builder unit tests.
- Future-roadmap impact summary:
  - Stage 18 can reuse shared container records, path-safety helpers, redaction,
    and fake-command patterns without inheriting Docker-only flags.
  - Stage 18 may still need explicit path translation or scheduler/container
    resource composition; Stage 17 records those as revisit triggers rather than
    implementing them early.
  - Stage 19 can add retry, timeout, failure category, and transaction policy
    around existing executor result metadata.
  - Stage 20 can project committed Docker/container facts into runtime events
    and observe-only event sinks.
  - Stage 21 can consume log/staging/materialization facts for cleanup without
    treating container staging as authority truth.
- Generic interface, adapter, and protocol assessment:
  - The shared records are reusable enough if they stay plain-data,
    import-light, and limited to image/workdir/mount/environment/resource
    intent.
  - `DockerCommandRunner` should remain a narrow Docker adapter protocol for
    Stage 17; a cross-runtime command-runner abstraction is premature.
  - Executor descriptors are the right place to claim `container`/`docker`
    adapter namespaces and resource capabilities without importing Docker.
- Planning revisions required:
  - Completed in this review: DAQ classifications, design triage, practical
    notes, accepted debt/risk, implementation-readiness, open questions, and
    handoff notes were updated.
  - Remaining planning work is examples, validation strategy, and phase
    shaping; design-safety itself does not block implementation-plan drafting
    once those later sections are complete.
- Accepted risks:
  - Path parity is intentionally less flexible than path translation.
  - Docker digest metadata may be absent when cheap local inspection is
    unavailable.
  - Environment key names may appear in selected summaries, but values and raw
    adapter payloads must not.
  - Default validation remains fake-command based, with real Docker acceptance
    optional.
- Revisit triggers:
  - Stage 18 needs incompatible generic `container` fields, explicit path
    translation, or scheduler/container resource composition.
  - A future image-lock, image-as-semantic-input, secret-management, or
    expensive-preflight stage changes provenance or redaction policy.
  - Maintainers require live Docker acceptance evidence before release.

## Practical Design Notes

Public Python API surface:

- Lazy exports for `DockerExecutor` and likely Docker/container option records.
- Shared container records remain under executor ownership, not root `loom`
  exports in Stage 17.
- The `container` adapter namespace is public runtime/profile config surface,
  but only for narrow plain-data image/workdir/mount/environment/resource
  intent. Docker-only behavior remains under `docker`.

CLI surface:

- `loom run CONFIG --executor docker`.
- Existing preflight command paths recognize the selected Docker executor.
- No Docker-specific command group in Stage 17.

Persisted records and file layout:

- Reuse stage worker request/result, status, failure, provenance, and log
  paths.
- Persist Docker executor metadata under existing result/failure metadata
  shapes.
- No new container-specific run directory tree unless implementation proves a
  narrow command metadata sidecar is needed.
- `runtime.json` must not persist raw adapter payloads or environment values.
  Docker executor metadata may persist selected environment key summaries and
  redacted values only where needed for diagnosis.

Import boundaries and dependencies:

- No Docker SDK.
- No Docker import or daemon dependency during package import, CLI help,
  non-Docker preflight, or default tests.
- Docker command execution stays inside Docker executor module.

Failure modes and diagnostics:

- Missing command, invalid options, invalid mounts, missing env, unsupported
  resources, Docker process failure, missing/invalid worker result, and
  process/worker conflicts map to structured failures or preflight checks.
- Non-local, non-mountable, or non-path-parity run directories and local
  artifact roots fail with explicit diagnostics rather than implicit path
  rewriting.

Extension points and flexibility boundaries:

- Shared container records are reusable by Stage 18.
- Docker-specific flags do not become generic container contract by accident.
- Path rewriting, advanced GPU mapping, image pulls, registry auth, and
  whole-controller containerization remain explicit future work.

Generic interfaces, adapters, and protocols:

- `DockerCommandRunner` is narrow and fakeable.
- Executor descriptor records claim Docker/container adapter namespaces and
  capabilities.
- Shared container records are plain-data value objects, not a universal
  orchestrator protocol.
- CPU and memory capabilities should state the Docker enforcement expectation
  precisely; GPU requests are unsupported/error in Stage 17.

Future-roadmap compatibility:

- Stage 18 can reuse records/helpers for Apptainer/Singularity.
- Stage 19 can add shared retry/timeout/failure/transaction policy around
  recorded Docker facts.
- Stage 20 can add runtime event and observe-only event-sink projections over
  committed Docker facts.
- Stage 21 can add cleanup policy without changing Stage 17 authority or
  artifact semantics.

Maintainability assessment:

- Maintainability depends on keeping lifecycle in `PipelineRunner`, Docker
  invocation in the Docker executor, shared container records import-light, and
  CLI/diagnostics as consumers only.

Extensibility assessment:

- The shape is extensible if shared container concepts stay small and
  Docker-specific behavior remains namespaced. The confirmed `container` plus
  optional `docker` namespace split is the main Stage 18 reuse point and should
  be pressure-tested in design-safety review.

Flexibility and expansion assessment:

- Path parity and explicit env are intentionally conservative. They simplify
  Stage 17 and leave path translation, secret management, and advanced GPU
  policy for later roadmap work.

Scalability and future compatibility:

- Stage 17 remains serial/runner-mediated like subprocess execution. It does
  not add container pools or orchestration, which keeps future queue/scheduler
  work from depending on local Docker assumptions.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Path-parity mounts only | Avoids rewriting persisted run-store and artifact paths in the first Docker executor. | Stage 18 or remote-store/container workflows require explicit host/container path translation. |
| GPU mapping unsupported | Advanced GPU behavior is deferred by the roadmap. | A future roadmap stage selects a concrete GPU mapping policy. |
| No default real Docker validation | Keeps default checks deterministic and available without Docker. | Maintainers require live Docker acceptance evidence before release. |
| Best-effort image digest metadata | Avoids default pulls, registry contacts, or daemon-heavy probes. | Image lock files, image-as-semantic-input policy, or release acceptance requires stronger image identity guarantees. |
| Narrow public `container` namespace | Preserves Stage 18 reuse without designing a full container orchestration API. | Stage 18 needs incompatible generic fields or repeated Docker-specific exceptions appear in shared records. |

## Examples And Demonstrations

| Example | Behavior demonstrated | Loom context | Required docs/tests | Status |
| --- | --- | --- | --- | --- |
| Direct/prepared stage Docker execution | A prepared stage attempt is run through `docker run` with the existing `loom stage run --run-uri ... --stage ... --attempt ... --format json` worker command inside the container. The example should make path-parity mounts, workdir, selected env, redacted command projection, and worker result handoff visible. | Stage-worker path used by `SubprocessExecutor` and future submitted/container runtimes. | Example fixture or docs snippet plus fake-runner executor integration test that proves the built Docker argv drives the normal prepared-worker request/result path. | planned |
| Normal pipeline Docker execution | A small normal Loom pipeline runs with `loom run CONFIG --executor docker`; selected stage attempts execute in Docker containers while the controller, scheduler, run store, and finalization remain host-side Loom behavior. | User-facing local/CI workflow requested by the user. | Example config showing `adapter_options.container` and optional `adapter_options.docker` at run/profile or per-stage scope; CLI/e2e-style fake-runner test that asserts the pipeline completes through the Docker executor. | planned |
| Docker preflight | Selected-executor preflight reports Docker command availability, image reference presence, mount source/target validity, run-directory writability, artifact-root visibility, required env availability, and unsupported resource mappings without pulling images or contacting registries. | Preflight diagnostics for users before a Docker run. | Contract tests for stable check IDs and example output for both pass and actionable fail cases. | planned |
| Inspectable Docker failure | Docker process failures, missing worker result, invalid worker result, worker-result failure, and process/worker conflicts are surfaced through existing Loom status, logs, failure, and diagnostics with redacted Docker metadata. | Debugging and CI failure workflow. | Fake-runner integration tests and docs example showing where users inspect logs/failure facts; assertions that raw env values and raw adapter payloads are absent. | planned |
| Runtime/profile configuration examples | Users can configure shared image/workdir/mount/env/resource intent under `container` and Docker-specific flags under `docker` without changing semantic pipeline stage specs. | Durable public config shape and Stage 18 reuse point. | Docs examples plus config/profile contract tests for run-level, profile-level, and per-stage adapter options; invalid namespace or invalid field diagnostics. | planned |
| Optional real Docker smoke | Maintainers may run a live Docker smoke against a tiny local pipeline when explicitly enabled; this is not part of default CI or `make validate-pr`. | Release or maintainer acceptance evidence, not default package validation. | Marked/env-gated test or documented manual command that skips unless Docker is explicitly enabled and available. | optional |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Package and import boundaries | Docker support does not require Docker, network, a daemon, or the Docker SDK during package import, CLI help, non-Docker preflight, or default tests. | Lazy exports for `DockerExecutor`; shared records remain import-light; existing local/subprocess/SLURM import behavior unchanged. | Package/import tests and regression checks. | `tests/unit/...` plus `make validate-pr` final gate. | planned |
| Shared container records | Image, workdir, mounts, environment handoff, resource intent, and redacted command projections are strict, serializable, Stage 18-neutral value records. | Valid/invalid records, serialization, absolute target validation, mount modes, path parity markers, env selected keys, redacted metadata, no raw adapter payload persistence. | Unit and contract tests. | `tests/unit/loom/pipeline/executors/test_containers.py` and profile/config contract tests. | planned |
| Runtime/profile adapter options | `container` and optional `docker` adapter namespaces merge through existing runtime/profile behavior without semantic stage-spec Docker fields. | Run-level, profile-level, per-stage overrides, unclaimed namespace diagnostics, invalid field failures, descriptor namespace claims. | Contract tests. | Runtime/profile tests and descriptor tests. | planned |
| Docker command builder | `docker run` argv is deterministic, shell-free, redaction-safe, and includes image, workdir, mounts, env, CPU/memory flags, log/result paths, and the prepared worker command. | Arg ordering, mount/workdir construction, CPU/memory mapping, unsupported GPU handling, env passing without persistence, redacted projection, no default pull/registry flags. | Unit tests. | `tests/unit/loom/pipeline/executors/docker/test_commands.py`. | planned |
| Docker command runner protocol | Docker command execution is fakeable and subprocess-backed by default without spreading direct subprocess calls through the executor. | Runner protocol, result record, bounded stdout/stderr, timing/error facts, subprocess exception mapping, fake-runner behavior. | Unit tests. | Docker executor command-runner tests. | planned |
| Docker executor prepared-worker integration | `DockerExecutor` consumes prepared worker requests, launches the Docker command, reads standard worker results, and returns `StageExecutionResult` without owning parent finalization. | Successful worker result, missing result, invalid result, failed result, nonzero Docker process, process/worker conflict, log path metadata, run-store status preservation. | Integration tests with fake Docker runner. | `tests/integration/...` or executor integration tests near subprocess coverage. | planned |
| Failure metadata and redaction | Persisted command, failure, provenance, diagnostics, and runtime metadata do not contain raw env values or raw adapter payloads. | Secret-looking keys/values, selected key summaries, redacted command metadata, failure details, `runtime.json` metadata boundaries. | Unit and integration tests. | Executor metadata and runtime serialization tests. | planned |
| Provenance | Docker image reference, Docker runtime/version when cheap, image digest when cheaply available, mount/env/resource summaries, exit code, and timeout/process facts are recorded as executor/provenance metadata without changing semantic fingerprints. | Digest available/unavailable, command unavailable, no pull/registry access by default, no mandatory fingerprint change. | Unit and contract tests. | Provenance and executor metadata tests. | planned |
| Preflight and diagnostics | Docker selected-executor checks are cheap by default, stable, structured, and actionable. | Command availability, image reference presence, mount sources/targets, run-dir writability, artifact-root visibility, required env, CPU/memory support, GPU unsupported, JSON output/check IDs. | Contract and integration tests. | `tests/contracts/...`, `tests/unit/loom/diagnostics/...`. | planned |
| CLI and examples | `loom run CONFIG --executor docker` and preflight select the Docker executor without adding a Docker command group. Examples use the same product path as real execution. | CLI executor resolution, unsupported executor messaging update, example configs, fake-runner example tests, docs snippets. | CLI/e2e-style fake tests and docs validation. | Existing CLI tests plus example fixtures. | planned |
| Optional live Docker acceptance | A real Docker smoke can validate a tiny local pipeline when explicitly enabled, but is skipped by default. | Skip behavior, no default daemon dependency, no registry/network expectation beyond a user-provided local image or explicit maintainer setup. | Opt-in test or manual acceptance note. | Marked/env-gated test outside `make validate-pr` defaults. | optional |
| Existing executor regressions | Local, subprocess, and SLURM execution, preflight, descriptors, and runtime/profile parsing continue to behave as before. | Existing tests plus targeted regressions around executor selection and adapter namespaces. | Full PR gate. | `make validate-pr`; `make test-summary` before PR preparation. | planned |

## Phase Sketch

### Phase 1 - Container Contracts and Runtime Descriptor

Goal:

- Establish the shared container configuration and capability contract that
  Docker will use and Stage 18 can reuse.

Scope:

- Add import-light shared container records/helpers under executor ownership.
- Add Docker executor descriptor/capability declarations and adapter namespace
  claims for `container` and `docker`.
- Extend runtime/profile parsing and validation only as needed for those
  namespaces.
- Record redaction, path-parity, resource support, and no-raw-adapter-payload
  contract tests.

Out of scope:

- Docker command execution.
- Docker preflight check execution beyond descriptor/config shape.
- Apptainer/Singularity or scheduler/container composition.
- Semantic stage-spec Docker fields.

Acceptance criteria:

- Container records cover image, workdir, mounts, explicit environment
  handoff, resource intent, and redacted metadata projection.
- Docker descriptor claims `container` and `docker` namespaces and accurately
  reports CPU/memory support plus GPU unsupported status.
- Invalid container/Docker config fails with structured diagnostics or
  validation errors before command construction.
- Shared records do not import Docker-specific command code, CLI presentation,
  diagnostics presentation, optional SDKs, or daemon-facing behavior.

Test expectations:

- Package: import-boundary tests for shared container records and lazy Docker
  exports.
- Unit: value-record, redaction, mount target, path-parity marker, env, and
  resource mapping tests.
- Contract: runtime/profile adapter namespace and descriptor capability tests.
- Integration: none required beyond config/descriptor wiring.
- E2E: none.
- Opt-in: none.

Design impact:

- This phase creates the durable public config and reusable record shape.
  It must keep generic `container` records narrow and Docker-only fields
  namespaced.

Future compatibility:

- Stage 18 should be able to reuse generic records without inheriting Docker
  flags or host/path translation promises.

Alternatives rejected:

- Docker-only public config for all fields.
- Semantic pipeline stage-spec Docker fields.
- A broad generic orchestration API.

Debt introduced:

- Path parity remains the only Stage 17 mount strategy.

Reviewability:

- Review should focus on public config shape, import boundaries, descriptor
  capabilities, and redaction/persistence tests.

### Phase 2 - Docker Command Builder and Runner

Goal:

- Build deterministic, redaction-safe Docker CLI invocations and fakeable
  command-result handling without integrating with the runner yet.

Scope:

- Add Docker-specific options, command builder, command runner protocol,
  subprocess-backed runner, bounded result record, and metadata projection.
- Implement Docker argv construction for image, workdir, mounts, selected env,
  CPU/memory flags, run/artifact path parity, and prepared worker command
  embedding.
- Add cheap metadata helpers for Docker version and best-effort image digest
  when available without pulls or registry access.

Out of scope:

- Parent runner integration and worker-result finalization.
- Preflight presentation and stable check IDs.
- Real Docker acceptance as a required test.

Acceptance criteria:

- Built commands are argv lists, not shell strings.
- Redacted command projections omit raw env values and secret-looking values.
- Docker process results preserve return code, bounded stdout/stderr,
  process errors, timing facts, timeout facts where available, and log metadata.
- CPU/memory flags are generated only for supported requests; GPU requests
  fail closed or produce unsupported mapping diagnostics for later phases to
  surface.
- Metadata helpers are best-effort and never pull images or contact registries
  by default.

Test expectations:

- Package: Docker module import does not require Docker SDK or daemon access.
- Unit: command argv ordering, mounts, workdir, env, resource flags, redaction,
  bounded output, subprocess errors, version/digest helper outcomes.
- Contract: command/result records serialize only safe metadata.
- Integration: fake runner drives command builder through realistic prepared
  worker command input.
- E2E: none.
- Opt-in: none.

Design impact:

- This phase locks the Docker adapter protocol shape but keeps it Docker-local
  rather than creating a premature cross-runtime runner abstraction.

Future compatibility:

- Stage 18 can copy the command-runner pattern without depending on Docker
  argv fields.

Alternatives rejected:

- Docker SDK dependency.
- Direct subprocess calls throughout executor logic.
- Persisting shell command strings or raw environment values.

Debt introduced:

- Real daemon behavior is not proven by default tests.

Reviewability:

- Review should verify command construction is deterministic, redacted,
  shell-free, fakeable, and cheap by default.

### Phase 3 - Docker Executor Integration

Goal:

- Run prepared stage attempts through Docker while preserving existing runner,
  worker-result, run-store, artifact-store, failure, and log semantics.

Scope:

- Add `DockerExecutor` with `requires_prepared_worker_request = True`.
- Wire CLI executor selection so `loom run CONFIG --executor docker` uses the
  Docker executor.
- Validate Docker/container options for each prepared worker request.
- Launch Docker through the command runner, read the standard worker result,
  and return `StageExecutionResult` with structured executor metadata.
- Map success, Docker process failure, missing worker result, invalid worker
  result, failed worker result, process/worker conflict, and log paths.

Out of scope:

- Broad retry or timeout policy beyond recording available facts.
- Docker-specific CLI command group.
- Parent-owned finalization, artifact index writes, or run-store status
  authority inside the Docker executor.
- Whole-controller-in-container mode.

Acceptance criteria:

- A fake-runner integration test completes a small pipeline through
  `loom run --executor docker` using the prepared stage-worker path.
- Docker executor failures are inspectable through existing Loom failure and
  log surfaces.
- Local/subprocess/SLURM executor behavior remains unchanged.
- Runtime and executor metadata do not persist raw env values or raw adapter
  payloads.

Test expectations:

- Package: lazy Python exports for Docker executor.
- Unit: executor option validation and failure mapping.
- Contract: `StageExecutionResult` metadata/failure shape and no raw metadata
  persistence.
- Integration: fake Docker runner through prepared worker request/result,
  successful pipeline, missing/invalid/failed result, nonzero process, conflict
  mapping, log path behavior.
- E2E: CLI-style fake-runner test for `loom run --executor docker`.
- Opt-in: none required.

Design impact:

- This phase connects public user behavior to the existing execution lifecycle
  without changing runner ownership.

Future compatibility:

- Stage 19 can wrap recorded process/failure facts with shared reliability
  policy. Stage 20 can project committed Docker facts into runtime events.
  Stage 21 can consume logs/staging facts without Docker owning cleanup.

Alternatives rejected:

- New runner mode.
- Docker executor writing final statuses or artifact indexes directly.
- Controller-in-container execution.

Debt introduced:

- Timeout enforcement remains limited to process facts until Stage 19 defines
  shared policy.

Reviewability:

- Review should focus on lifecycle ownership, parity with subprocess semantics,
  failure inspectability, and regression safety for existing executors.

### Phase 4 - Docker Preflight and Diagnostics

Goal:

- Add cheap selected-executor Docker diagnostics that catch common runtime,
  filesystem, environment, and resource issues before launch.

Scope:

- Add stable Docker check IDs and diagnostic models where needed.
- Extend preflight to check Docker command availability, image reference
  presence, container/Docker option shape, mount source/target validity,
  run-directory writability, local artifact-root visibility, required env
  availability, CPU/memory support, and GPU unsupported errors.
- Ensure JSON and presentation output remain structured and actionable.

Out of scope:

- Default image pulls, registry auth, network probes, or daemon-heavy image
  inspection.
- Expensive live-run smoke tests.
- Non-Docker container runtimes.

Acceptance criteria:

- Docker preflight runs only when Docker is selected or explicitly inspected.
- Missing command/image/mount/env/resource cases produce stable check IDs with
  actionable details.
- Cheap preflight does not require a real Docker daemon, image registry, or
  network access by default.
- Existing preflight for local/subprocess/SLURM remains unchanged.

Test expectations:

- Package: diagnostics imports do not import Docker executor command execution.
- Unit: preflight helpers for each pass/fail case.
- Contract: stable check ID and JSON output tests.
- Integration: selected-executor preflight with fake filesystem/env/resource
  inputs.
- E2E: CLI/preflight presentation smoke using fake checks where existing tests
  support it.
- Opt-in: none.

Design impact:

- This phase locks user-visible diagnostics and check IDs.

Future compatibility:

- Stage 18 can mirror the selected-executor preflight pattern for
  Apptainer/Singularity and scheduler/container composition.

Alternatives rejected:

- Pulling or inspecting images by default.
- Registry authentication probes.
- Collapsing Docker checks into generic filesystem errors without Docker
  context.

Debt introduced:

- Image availability/digest confidence remains best-effort unless an opt-in
  expensive probe is added later.

Reviewability:

- Review should focus on check-ID stability, cheap/default behavior, actionable
  messages, and no accidental daemon/network dependency.

### Phase 5 - Examples, Documentation, and Acceptance Hardening

Goal:

- Provide the requested Docker stage and pipeline examples, then harden the
  final validation evidence for PR review.

Scope:

- Add docs/examples for direct/prepared stage Docker execution, normal
  `loom run --executor docker` pipeline execution, Docker preflight, and
  inspectable Docker failures.
- Ensure examples use `container` and `docker` adapter namespaces and do not
  imply containers are a security sandbox.
- Add daemon-free example tests using fake Docker runners.
- Add optional real Docker smoke or manual acceptance notes gated outside
  default validation if implementation scope allows.
- Run full PR validation and record suite evidence for the implementation plan
  and PR body.

Out of scope:

- Image build, registry auth, Compose, Kubernetes, Apptainer/Singularity,
  advanced GPU mapping, and controller-in-container examples.
- Requiring real Docker in `make validate-pr`.

Acceptance criteria:

- Users have copyable examples for running stages and full pipelines in Docker
  environments through the actual Docker executor path.
- Failure and preflight examples show how to inspect issues without exposing
  secrets.
- Default validation remains daemon-free.
- Optional live Docker coverage is clearly marked and skipped unless explicitly
  enabled.

Test expectations:

- Package: final import regression through `make validate-pr`.
- Unit: any docs/example helper coverage needed for stable fixtures.
- Contract: docs/config examples parse and validate.
- Integration: fake-runner example tests for stage and pipeline workflows.
- E2E: CLI/example tests where existing harness supports them.
- Opt-in: optional marked real Docker smoke.

Design impact:

- This phase turns the feature into an understandable user workflow and
  verifies that examples exercise product code rather than demo-only paths.

Future compatibility:

- Stage 18 can follow the same examples pattern for Apptainer/Singularity
  without changing Stage 17 docs.

Alternatives rejected:

- Requiring real Docker for examples.
- Documenting whole-controller-in-container workflows.
- Presenting Docker as an isolation boundary for untrusted code.

Debt introduced:

- Optional live Docker evidence may remain manual or skipped until maintainers
  require release-level acceptance.

Reviewability:

- Review should focus on docs accuracy, example testability, default validation
  evidence, and preserving explicit non-goals.

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | FR-1 through FR-10 confirmed from roadmap, feature docs, and user examples request. | pass | None. |
| Requirement-to-design traceability | Behavior baseline confirmed; DAQ-1 through DAQ-12 confirmed and design-safety reviewed. | pass | Carry recorded recommendations into examples, validation, phase shaping, and implementation-plan drafting. |
| Design-safety review completed | Completed on 2026-05-16 with no blockers. | pass | None. |
| Future-roadmap impact considered | Stage 18/19/20/21 impacts recorded; path translation, GPU, image identity, secret management, and expensive preflight remain explicit revisit triggers. | pass | Carry revisit triggers forward. |
| Generic interface, adapter, and protocol flexibility considered | Shared `container` namespace, optional `docker` namespace, path-parity mounts, resource mapping, preflight, and fake-command protocol reviewed. | pass | Keep shared records narrow and import-light. |
| Example-to-validation traceability | Examples and validation strategy map each requested Docker workflow to daemon-free default tests and optional real Docker acceptance. | pass | Carry example obligations into the implementation plan. |
| Phase-shaping readiness | Phase sketch covers public config/contracts, Docker command builder, executor integration, preflight/diagnostics, and examples/acceptance hardening. | pass | Convert this sketch into implementation-plan phases after final confirmation. |
| Unresolved blocked or needs-discussion functionality or design decisions | No unresolved blocked or needs-discussion functionality or design decisions remain after design-safety review. | pass | None. |

Readiness result:

- Status: confirmed; ready for implementation-plan drafting
- Implementation-plan drafting blockers:
  - None in the planning artifact.
  - Explicit final user confirmation received on 2026-05-16.
- Accepted risks:
  - Path-parity mounts only.
  - GPU mapping unsupported.
  - Best-effort image digest metadata.
  - No default real Docker validation.
  - Narrow public `container` namespace.
- Assumptions to carry forward:
  - Per-stage Docker execution, Docker CLI, no Docker SDK, fake-command default
    validation, and no security-sandbox guarantee are confirmed Stage 17
    defaults.
  - Examples and phase boundaries are scope guides for the implementation plan;
    implementation phases still require the normal implementation-plan quality
    gate before phase execution begins.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Do you have clarifying questions about the Stage 17 briefing before capability triage starts? | Roadmap framing | Pause and answer clarifications before moving on. | closed; no questions raised |
| What should Stage 17 optimize for: local/CI per-stage reproducibility, parity with subprocess semantics, shortest path to Stage 18 reuse, or another priority? | Roadmap framing and intent discovery | Optimize for reliable per-stage Docker executor parity with local/subprocess, while preserving reusable container records for Stage 18. | closed; user agreed |
| Who is the primary target user for v17: local developer, CI maintainer, research pipeline author, or future cluster/container integrator? | User intent and examples | Local developer and CI maintainer, without blocking future cluster reuse. | closed; user agreed |
| Which concrete workflows must be treated as Stage 17 success examples? | Intent discovery and validation | `loom run CONFIG --executor docker` for a small local pipeline, failure inspection, and preflight. | closed; user agreed |
| Which operational constraints should be hard requirements rather than defaults? | Intent discovery and design boundaries | No Docker SDK, no default daemon/network dependency in tests, no automatic pulls, explicit mounts/env only. | closed; user agreed |
| Does the candidate capability sort and FR-1 through FR-9 set match Stage 17 scope before functionality agreement starts? | Capability triage | Include FR-1 through FR-9; keep real Docker acceptance optional; defer platform/orchestration work. | closed; user agreed |
| Should pipeline examples mean full Loom pipeline runs where stage attempts execute in Docker containers, while whole-controller-in-container mode remains deferred? | Functionality agreement | Yes. | closed; user agreed |
| Does the drafted behavior baseline accurately reflect the confirmed Stage 17 functionality before the context checkpoint? | Functionality and behavior confirmation | Yes. | closed; user agreed |
| Should Stage 17 expose a shared `container` adapter namespace for generic fields plus optional `docker` namespace for Docker-specific flags? | Design agreement | Yes. | closed; user agreed |
| Did design-safety review find any blockers or decisions needing reopened discussion? | Design safety review and implementation-plan readiness | No; DAQ-1 through DAQ-12 remain confirmed with recorded recommendations and accepted risks. | closed; design-safety passed |
| Is this completed planning artifact acceptable as the primary source for drafting `docs/roadmap/stage-17/implementation-plan.md`? | Final planning confirmation and handoff | Yes. | closed; user approved on 2026-05-16 |

## Handoff Notes

Implementation-plan draft inputs:

- Ready; explicit final planning confirmation received on 2026-05-16.
- Use this planning artifact as the primary source for
  `docs/roadmap/stage-17/implementation-plan.md`.
- Carry forward FR-1 through FR-10, DAQ-1 through DAQ-12, design-safety
  recommendations, example obligations, validation strategy, phase sketch,
  accepted risks, and revisit triggers.

Design-safety review result:

- Passed on 2026-05-16 with no blockers.
- DAQ-6 and DAQ-9 auto-approval was upheld.
- DAQ-2 is a recorded recommendation after user confirmation and design-safety
  review; no unresolved `needs discussion` decisions remain.
- Recorded recommendations to carry forward: narrow shared `container`
  namespace, Docker-specific `docker` namespace, path-parity fail-closed
  semantics, strict redaction/no raw adapter persistence, precise resource
  capabilities, cheap preflight/provenance defaults, and fake executor-level
  command validation.

Validation and phase-shaping inputs:

- Ready.
- Examples require direct/prepared stage Docker execution, normal
  `loom run --executor docker` pipeline execution, Docker preflight,
  inspectable failures, runtime/profile configuration snippets, and optional
  real Docker smoke guidance.
- Validation requires package/import, unit, contract, integration, CLI/e2e
  fake-runner, optional live Docker, and full PR-gate evidence.
- Phase sketch should become five implementation-plan phases:
  shared container contracts and runtime descriptor; Docker command builder and
  runner; Docker executor integration; Docker preflight and diagnostics; and
  examples, documentation, and acceptance hardening.

Plan-quality-gate risks:

- Risks accepted or bounded by design-safety review:
  Docker option/config ownership, path translation and artifact-root mount
  semantics, redaction policy, resource mapping support, stable preflight check
  IDs, and Stage 18 reusable container shape.
- Remaining planning risks before implementation-plan drafting:
  none.
- The implementation plan must still pass the normal plan quality gate before
  phase execution begins.

Assumptions to carry forward:

- Docker remains optional and CLI-backed.
- Default validation remains fake-command and no-network.
- Container execution is not a security sandbox for untrusted code.
- The controller stays outside Docker; Docker runs selected stage attempts.
- Docker choices remain provenance/executor metadata by default, not mandatory
  semantic fingerprint inputs.
- No phase execution plans or code implementation should start from this
  planning artifact until the implementation plan is drafted, refined, and
  quality-gated.
