# Roadmap Stage 18 Planning: HPC Container Execution

## Metadata

- Roadmap stage: v18
- Source roadmap: `docs/roadmap.md`
- Previous version status:
  - `docs/roadmap/stage-17/planning.md` exists in the current checkout as an
    untracked working-tree artifact and records Stage 17 planning as confirmed.
  - `docs/roadmap/stage-17/implementation-plan.md` exists in the current
    checkout as an untracked working-tree artifact and records Stage 17 Docker
    container executor phases as pending.
  - The current checkout does not yet contain Docker/container source modules;
    Stage 18 planning treats the Stage 17 plan as expected prerequisite context
    and carries a revisit trigger if Stage 17 implementation changes shared
    container contracts.
- Planning artifact status: confirmed
- Current discussion stage: implementation-plan draft created from confirmed planning artifact
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Capability triage and candidate functional requirements: confirmed
  - Functionality agreement review: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: completed
  - Design agreement review: completed
  - Design safety review: passed
  - Examples and validation strategy: completed
  - Phase shaping: completed
  - Implementation readiness: completed
  - Handoff: completed
- Related implementation plan: `docs/roadmap/stage-18/implementation-plan.md` draft created
- Related feature docs:
  - `docs/features/container-executors.md`
  - `docs/features/slurm.md`
  - `docs/features/execution.md`
  - `docs/features/runtime-resources.md`
  - `docs/features/preflight.md`
  - `docs/features/provenance.md`
  - `docs/features/reliability.md`
  - `docs/features/testing.md`
- Blockers:
  - None for the roadmap-stage planning workflow.
- Implementation-plan drafting result and phase-execution constraints:
  - Stage 17 source refresh was performed while drafting
    `docs/roadmap/stage-18/implementation-plan.md`; the current checkout still
    does not contain Docker/shared-container source modules, so the draft
    records Stage 17 source absence as an accepted risk and a Phase 1
    execution-planning prerequisite.
  - `.sif` image build/construction support is in scope and must remain
    explicit, fakeable by default, and bounded to user-authored definition files
    plus explicit `apptainer build` sources.
  - Build-service support is local-only for Stage 18 because current Apptainer
    remote endpoints do not provide the old remote-build path; external or site
    build-service adapters remain deferred.
  - Docker and Apptainer both need the shared dynamic build layer. Stage 18 owns
    the shared/generic `container_build` phase, with Docker and
    Apptainer-specific semantics handled by adapters where needed.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` v18 | Stage 18 supports Apptainer/Singularity and the common SLURM plus Apptainer execution path used on HPC systems. | roadmap scope | Primary outcome is HPC container execution, not a general container platform. |
| `docs/roadmap.md` v18 | Implementation scope includes Apptainer/Singularity command builder and executor, runtime detection for `apptainer` and `singularity`, bind mount/workdir behavior, image/runtime provenance, resource mapping with v4 and v6/v7, SLURM plus Apptainer composition, preflight, and fake-command tests. | confirmed capabilities | These items seeded capability triage and are now confirmed in the behavior baseline. |
| `docs/roadmap.md` v18 | Exit criteria require Apptainer/Singularity to execute stages through the same worker contract as Docker, dry-run SLURM plus Apptainer scripts to be inspectable, and live SLURM plus Apptainer to reuse v7 submission paths. | acceptance boundary | Strongly suggests prepared-worker parity and no separate scheduler implementation. |
| `docs/roadmap.md` v18 | Defers MPI orchestration, multi-node container coordination, site-specific module loading, automatic image conversion, registry authentication, Kubernetes, and treating containers as a security boundary. | explicit deferrals | Keeps Stage 18 focused on CLI-backed Apptainer and SLURM script composition. |
| `docs/roadmap.md` v17 | Docker stage is expected to establish shared container records, path-parity mount assumptions, fake command testing, and Docker-specific executor behavior while deferring Apptainer/Singularity and SLURM-container composition. | prerequisite and reusable contract | Stage 18 should reuse or challenge Stage 17 shared `container` namespace rather than duplicate incompatible public config. |
| `docs/roadmap.md` v19 | Reliability policy follows containers and must support local, subprocess, SLURM, Docker, and Apptainer/Singularity paths. | successor compatibility | Stage 18 should record process/container/scheduler facts generically enough for Stage 19 retry, timeout, failure, and transaction policy. |
| `docs/features/container-executors.md` | Recommended executor names are `docker`, `apptainer`, and `singularity`; `singularity` may alias Apptainer if that command is installed. | executor naming evidence | Design review resolved this as `apptainer` primary with `singularity` as a compatible command/executor name that records selected command identity. |
| `docs/features/container-executors.md` | Apptainer executor responsibilities include finding `apptainer` or `singularity`, constructing `apptainer exec`, applying bind mounts, working directory, selected environment, image path or URI, stdout/stderr capture, and exit code. | standalone Apptainer behavior | Supports a CLI-backed, SDK-free executor shape. |
| `docs/features/container-executors.md` | SLURM plus containers should compose by having submitted scripts invoke the container runtime, where the container command runs the stage wrapper and normal Loom state records are reused. | scheduler/container composition | Stage 18 should not bypass submitted-operation manifests or authority state. |
| `docs/features/container-executors.md` | Containerized local artifact stores require host artifact roots to be mounted into the container, with matching or explicitly mapped container paths, and remote stores require backend dependencies and credentials inside the container. | artifact and mount behavior | Path parity from Stage 17 may need validation against HPC filesystems and Apptainer bind behavior. |
| `docs/features/container-executors.md` | Preflight should check runtime command availability, image reference presence, mount sources, run-directory writability, required environment variables, resource mapping support, and selected executor plugin availability. | diagnostics | Default checks should be cheap and avoid pulls or network access. |
| `docs/features/container-executors.md` | Core tests should use fake commands/builders; real Docker or Apptainer integration tests should be optional. | validation strategy | Stage 18 default validation should not require a real cluster or container runtime. |
| Apptainer User Guide, `apptainer build` and "Build a Container" | `apptainer build` produces a SIF by default and can build from definition files, local images/directories, Docker/OCI/library/ORAS/IPFS-style URIs, or sandbox directories. Temporary build space may need explicit configuration for large images. | SIF build/construction scope | User explicitly requested `.sif` build handling. Build support must remain explicit and fakeable by default because some targets require network, registry, or host build privileges. |
| Apptainer User Guide, "Definition Files" | Definition files contain a required header such as `Bootstrap` and optional sections such as `%files`, `%post`, `%environment`, `%test`, `%runscript`, labels, help, build args, and multi-stage sections. `%setup` runs on the host and is warned as risky; `%files` is safer for host-to-container copies. | definition-file build planning | Loom should record build inputs and warnings without inventing domain-specific image content. |
| Apptainer User Guide, "Fakeroot feature" | Unprivileged builds may use fakeroot; support depends on user namespaces, fakeroot command availability, setuid install mode, and bootstrap method restrictions. | build preflight and failure semantics | Stage 18 should diagnose build environment limitations instead of assuming images can always be built on the submission host. |
| Apptainer User Guide, `apptainer exec` | `apptainer exec` runs a command in a container and accepts SIF, sandbox, instance, and several URI-backed inputs. `--bind/-B`, `--cleanenv`, `--contain`, `--nv`, and related flags shape runtime behavior. | execution command construction | Direct executor and SLURM scripts should use explicit argv construction and redacted metadata. |
| Apptainer User Guide, "Bind Paths and Mounts" | User-defined bind paths use `--bind/-B` or `--mount`; default system binds may include home, CWD, `/tmp`, `/var/tmp`, `/dev`, `/proc`, and `/sys`; admins may disable user binds. | bind and preflight behavior | Loom should not assume default binds are sufficient or user binds are always permitted. |
| Apptainer User Guide, "Environment and Metadata" | Host environment variables are generally passed through by default, but `--cleanenv` gives a minimal environment; `--env`, `--env-file`, and `APPTAINERENV_` can set container variables. | environment handoff | Stage 18 should likely prefer explicit/clean environment handling for reproducibility and redaction. |
| Apptainer User Guide, "GPU and other Device Support" | `--nv` exposes NVIDIA devices/libraries, and `--rocm` supports AMD ROCm; host drivers and compatible libraries are required. | resource/GPU capability scope | GPU support can be modeled as explicit Apptainer flags plus preflight warnings, while SLURM owns allocation. |
| Apptainer User Guide, "Apptainer and MPI applications" | The standard MPI pattern is host `mpirun` launching `apptainer exec`; Slurm batch scripts can request nodes and run `mpirun -n ... apptainer exec ...`; `srun` can work when PMI/PMIx compatibility is satisfied. | SLURM composition and multi-node clarification | This supports script composition, but full MPI compatibility and rank orchestration are a larger design surface. |
| Apptainer User Guide, "Remote Endpoints" | Remote endpoints manage library, OCI registry, and keyserver services; current Apptainer docs state the former remote build option is not supported and point users toward unprivileged local builds. | build-service boundary | If Loom adds build-service support, it must be Loom/site-adapter design rather than assuming `apptainer build --remote` is available. |
| Docker Docs, "Build context" | Docker builds operate over a build context, which can be a local path, remote Git repository, tarball, stdin text, or other configured context. Instructions can access files from the context, and `.dockerignore` controls what is sent. | shared Docker build layer | Supports project/run/profile-level build specs and dynamic build contexts, not per-stage Dockerfiles. |
| Docker Docs, `docker buildx build` | Buildx supports explicit Dockerfile paths, stdin Dockerfiles, named build contexts, metadata output, cache controls, and loading/exporting build results. | Docker build-service shape | Useful for a fakeable Docker build command and build-result records with digest/provenance metadata. |
| Docker Docs, Dockerfile reference | Dockerfiles define image assembly instructions such as `FROM`, `ARG`, `COPY`, `RUN`, `ENV`, and `CMD`. | recipe boundary | Loom should not generate domain-specific Dockerfiles per stage; it can reference or materialize generic build recipes from project/run config. |
| Docker Docs, build cache optimization | Docker cache reuse depends on instruction order and files in the context; keeping context small and using cache/external cache features improves rebuild speed. | dynamic build policy | Stage planning should include cache keys, build policy, and context discipline instead of rebuilding every stage image blindly. |
| `docs/features/slurm.md` | V7 live SLURM uses generated scripts, submitted-operation manifests, `sbatch --parsable`, scheduler status/cancel records, and fake command runners by default. | SLURM reuse boundary | Stage 18 should compose generated script commands rather than create a parallel live scheduler path. |
| `docs/features/slurm.md` | V9-post authority deployment profiles require explicit authority handoff for live SLURM jobs and forbid treating local co-located authority as multi-host SLURM authority. | authority compatibility | Containerized stage commands must preserve authority handoff and redaction rules. |
| `docs/structure.md` | `loom.pipeline.executors` owns stage invocation mechanisms while execution, planning, and stores own lifecycle, DAG decisions, and durable state. | package boundary | Apptainer behavior belongs under executor ownership, with generic lifecycle kept in execution/runner code. |
| `docs/GLOSSARY.md` | `executor` runs one stage through a backend; `LocalRunStore` is local materialization, not authority truth. | vocabulary | Stage 18 should avoid treating generated scripts or container files as lifecycle authority. |
| `src/loom/pipeline/executors/subprocess.py` | `SubprocessExecutor` builds the stage-worker command, launches through an injectable runner, reads worker results, and normalizes process failures. | worker/executor precedent | Apptainer direct execution should likely mirror prepared-worker result handling. |
| `src/loom/pipeline/executors/slurm/planning.py` and `rendering.py` | SLURM dry-run planning builds `SlurmCommandArgv` records, maps resources to SBATCH directives, and renders deterministic scripts. | script composition precedent | SLURM plus Apptainer likely needs to replace or wrap generated command argv while preserving deterministic rendering. |
| `src/loom/pipeline/executors/slurm/commands.py` | SLURM command execution uses a fakeable command-runner protocol and bounded command result records. | fake command validation | Apptainer command execution should follow the fakeable runner pattern. |
| `src/loom/pipeline/runtime/capabilities.py` | Runtime descriptors currently include local, subprocess, `slurm-single-job`, and `slurm-afterok`; SLURM descriptors claim the `slurm` adapter namespace. | runtime descriptor gap | Stage 18 likely adds Apptainer/Singularity descriptors and may need a scheduler-container composition descriptor or adapter policy. |
| `src/loom/diagnostics/preflight.py` and `src/loom/diagnostics/models.py` | Preflight has stable group/check IDs for runtime, run URI, artifact backends, executor, resources, and filesystem; SLURM-specific checks are selected only for SLURM executors. | diagnostics integration | Stage 18 should add stable selected-executor checks without forcing Apptainer or SLURM checks for unrelated runs. |
| `src/loom/pipeline/runtime/profiles.py` | Runtime profiles support run-level and per-stage `adapter_options`. | config ownership | Supports container/apptainer/slurm adapter namespaces without adding semantic fields to pipeline stage specs. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Workflow and templates | `.codex/workflows/roadmap-stage-planning.md`, `.codex/prompts/roadmap-stage-planning-facilitate.md`, `.codex/templates/roadmap-stage-planning.md` | Workflow requires startup briefing, explicit clarification window, staged gates, design-safety review before implementation-plan drafting, and updates to this artifact after confirmed decisions. | Later passes must reread functionality/design prompts before those gates. |
| Roadmap docs | `docs/roadmap.md` v17-v19 and version overview | Stage 18 sits between Docker containers and reliability policy. It must reuse Docker/shared container patterns where possible and leave retry/timeout/transactions to Stage 19. | The local `docs/roadmap.md` file is modified in the working tree and the checkout is behind `origin/develop`; this artifact uses the current local contents. |
| Feature docs | `container-executors.md`, `slurm.md`, `execution.md`, `runtime-resources.md`, `preflight.md`, `provenance.md`, `reliability.md`, `testing.md` by targeted sections/search | Feature docs support optional CLI-backed Apptainer/Singularity, per-stage worker parity, SLURM script composition, cheap preflight, fake commands, and no security-sandbox promise. | Design pass should reread focused sections after functionality is confirmed, especially resource/GPU and artifact mount semantics. |
| External Apptainer docs | Official Apptainer user-guide pages for `build`, build overview, definition files, fakeroot, `exec`, bind paths, environment, GPU support, remote endpoints, and MPI/Slurm examples | User requested consultation before Stage 18 scope is locked. | Need final planning decisions for how much SIF build orchestration is core versus explicit build adapter behavior. |
| External Docker docs | Official Docker build context, Buildx, Dockerfile, and cache documentation | User clarified that Docker also needs the dynamic build-and-run layer. | Stage 18 will introduce the shared container-build layer with Docker-specific semantics where required. |
| Source and tests | Executor, runtime, diagnostics, SLURM, stage-worker, and test file listings; selected source files in `src/loom/pipeline/executors/`, `src/loom/pipeline/runtime/`, and `src/loom/diagnostics/` | Current source has local/subprocess/SLURM execution, runtime descriptors, adapter options, stable preflight IDs, fakeable command runners, and deterministic SLURM script rendering. No Docker, shared container, Apptainer, or Singularity modules are present in this checkout. | Stage 18 implementation-plan drafting must refresh source context after Stage 17 lands. |
| Prior or adjacent plans | `docs/roadmap/stage-17/planning.md`, `docs/roadmap/stage-17/implementation-plan.md`, `docs/roadmap/stage-19/planning.md`, `docs/roadmap/stage-19/implementation-plan.md` | Stage 17 plans a shared `container` namespace and Docker-specific `docker` namespace; Stage 19 explicitly carries a Stage 18 compatibility risk. | Adjacent stage artifacts are currently local/untracked; use as planning context, not as merged-source truth. |

## Roadmap Extraction

Baseline roadmap outcome:

- Add Apptainer/Singularity execution for prepared stage attempts through the
  same worker/result contract expected for Docker.
- Add explicit Apptainer SIF build/construction support, including deterministic
  command construction for `apptainer build`, source/definition input records,
  build output records, preflight diagnostics, and fake-command tests.
- Add an explicit local-only container build-service plan for image/SIF
  construction. Current Apptainer docs should not be treated as providing a
  built-in remote builder, and external/site build-service adapters stay
  deferred.
- Generalize the build layer across Docker and Apptainer so a run/profile can
  dynamically build a reusable image once, record the build output, and run
  multiple stages from that output without requiring one Dockerfile or
  Apptainer definition file per stage.
- Add deterministic Apptainer/Singularity command construction using CLI tools,
  with fakeable command execution and no Python SDK dependency.
- Detect `apptainer` and `singularity` command availability and resolve the
  runtime name/alias behavior deliberately.
- Validate HPC-friendly bind mounts, working directories, local artifact roots,
  run-directory writability, and selected environment handoff.
- Record image/runtime provenance for Apptainer/Singularity command version and
  image identity when cheaply available.
- Map generic resources where Apptainer can represent them directly and compose
  with SLURM resource enforcement where the scheduler owns CPU, memory, GPU, or
  wall-time behavior.
- Generate inspectable dry-run SLURM plus Apptainer scripts after standalone
  SLURM and standalone container paths are stable.
- Reuse v7 live SLURM submission paths for live SLURM plus Apptainer behavior
  rather than inventing a separate scheduler implementation.
- Add selected-executor preflight for container command availability, image
  reference/path presence, bind mount sources, run-directory writability,
  required environment variables, resource mapping, and scheduler/container
  compatibility.
- Add fake-command tests for build command construction, execution command
  construction, SLURM script composition, environment filtering, resource flags,
  and failure mapping.

Prerequisites:

- Stage 4 runtime options, resource requests, executor descriptors, and
  profile/adapter option merging.
- Stage 5 stage-worker and subprocess prepared-worker result contract.
- Stage 6/7 SLURM dry-run planning, script rendering, fake command runner,
  submitted-operation manifests, status, and cancellation paths.
- Stage 15/16 artifact-store and materialization contracts for local/external
  payload placement and operation evidence.
- Stage 17 shared container records, Docker executor precedent, path-parity
  policy, redaction rules, fake-command test pattern, and optional real runtime
  smoke strategy.
- Stage 17 Docker executor work or expected Docker executor contracts, plus an
  accepted handoff that Stage 18 introduces the shared build layer and adapts
  Docker-specific build semantics where required.

Primary feature docs:

- `container-executors.md`
- `slurm.md`
- `execution.md`
- `runtime-resources.md`
- `preflight.md`
- `provenance.md`
- `reliability.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- MPI orchestration.
- Multi-node container coordination.
- Site-specific module loading.
- Automatic image conversion beyond explicit, user-authored build sources.
- External or site build-service adapters.
- Registry authentication helpers.
- Kubernetes or cloud container orchestration.
- Docker Compose.
- Image build or publishing flows.
- Treating containers as a security boundary for untrusted code.
- Broad retry, timeout, transaction, event, cleanup, retention, or GC policy.
  Note: generic Docker/Apptainer build-and-run support is no longer deferred;
  what remains deferred is broad registry/auth, publishing, Compose, automatic
  conversion, and domain-specific image recipe generation.

Future-roadmap touchpoints:

- Stage 19 should consume Apptainer/Singularity process, failure, scheduler,
  timeout-capability, and transaction facts without needing backend-specific
  retry semantics.
- Stage 20 should be able to project committed container and scheduler facts
  into runtime events and observe-only sinks.
- Stage 21 should be able to reason about generated logs, bind-mounted local
  roots, staging records, and cleanup candidates without deleting authority
  state or external payloads.
- Future plugin discovery should be able to expose container or scheduler
  adapters without forcing heavy runtime dependencies into core imports.
- Future remote stores must either work through explicit mounted/materialized
  payloads or fail with clear backend-capability diagnostics.

Compatibility obligations:

- Local, subprocess, standalone SLURM, and Docker behavior should remain
  unchanged.
- Apptainer/Singularity must remain optional; default imports, CLI help,
  default preflight for unrelated executors, and default tests must not require
  a real Apptainer/Singularity install, a container image, a cluster, or
  network access.
- SIF build support must be explicit. Network-backed sources, registry-backed
  sources, privileged/fakeroot behavior, and build temporary-space choices must
  be recorded and diagnosable rather than implicit defaults.
- Build-service support must not assume Apptainer remote-build behavior. Stage
  18 uses a local-only Loom-owned build service/worker contract and preserves
  the same fake-command/default-offline validation policy.
- Docker and Apptainer build support should share build-request/build-result
  concepts where possible. Runtime-specific command construction belongs in
  adapter modules; shared records should not import Docker or Apptainer behavior.
- Stages should inherit/select named build outputs from run/profile config
  rather than requiring a container recipe per stage.
- Authored configs remain trusted project code, but persisted command,
  environment, provenance, and diagnostic metadata must redact secrets and avoid
  storing raw adapter payloads.
- Generated SLURM plus Apptainer scripts must preserve authority handoff,
  worker command semantics, submitted-operation manifests, scheduler status, and
  failure records.
- Container image/runtime identity is provenance by default unless a future
  semantic fingerprint policy explicitly changes that contract.

## Stage Briefing

What this stage is:

- Stage 18 is the HPC container execution stage. It adds
  Apptainer/Singularity support and the common pattern where SLURM jobs run
  stage-worker commands inside an Apptainer container.
- The stage is not a new workflow engine or cluster abstraction. It should
  adapt Loom's existing prepared-stage execution and SLURM submission paths to
  containerized HPC environments while preserving run-store, artifact,
  provenance, failure, and diagnostics semantics.
- Per user feedback, the stage should explicitly support Apptainer and should
  handle constructing/building `.sif` images rather than assuming every user
  supplies a prebuilt image out of band.
- Per user feedback, Stage 18 should include local-only build-service support
  for container construction. Because current Apptainer docs do not support the
  old remote builder flow, external or site-adapter build services are
  deliberately deferred.
- Per user feedback, Docker and Apptainer both need the build layer so Loom can
  dynamically build and run the selected container image. The user does not
  want a workflow where every stage needs its own Dockerfile or Apptainer
  definition file.

Why this stage exists:

- Docker is useful for local and CI container execution, but many HPC systems
  do not permit Docker daemons on compute nodes. Apptainer/Singularity is the
  common container runtime for those environments.
- Loom already has the building blocks this stage should compose: resource
  requests, prepared stage workers, subprocess execution, SLURM dry-run/live
  submission, local and external artifact contracts, preflight diagnostics, and
  planned shared container records from Stage 17.
- Users need the same research pipeline stage to run in a configured image on
  HPC without losing inspectable scripts, submitted job records, status/cancel
  behavior, redacted provenance, or local fake-command validation.
- Users also need the image that will run under SLURM to be produced by a
  recorded, inspectable Apptainer build path, so image provenance does not stop
  at "some `.sif` file exists."

Impacted or linked work:

- `loom.pipeline.executors` likely gains Apptainer/Singularity behavior and
  may reuse Stage 17 shared container records under executor ownership.
- Apptainer SIF build support likely needs executor-adjacent build records and
  command builders, while avoiding domain-specific image recipe generation.
- Local container build-service support likely needs a small
  build-request/build-result contract that records the definition/source, output
  image, worker identity, environment limits, and redacted logs without turning
  Loom into a container registry or image recipe generator.
- The shared container build layer likely needs named build specs at
  project/run/profile scope, build policies such as `never`, `if_missing`,
  `if_stale`, or `always`, cache key/fingerprint inputs, output references, and
  per-stage image selection by name rather than per-stage recipe files.
- `loom.pipeline.executors.slurm` likely gains composition points so generated
  single-job and afterok scripts can run prepared worker commands through
  Apptainer while preserving existing manifests and live submission.
- `loom.pipeline.runtime` likely gains Apptainer/Singularity descriptors and
  adapter namespace validation. A later design pass must decide whether
  SLURM-container composition is a new executor descriptor, a SLURM adapter
  option, an Apptainer adapter option, or a constrained combination of existing
  descriptors.
- `loom.diagnostics.preflight` likely gains selected-executor checks for
  Apptainer/Singularity and scheduler/container compatibility.
- `loom.pipeline.stores` and artifact/materialization contracts are relevant
  because local run directories and artifact roots must be visible inside
  containers through bind mounts or explicit materialization.
- `docs/features/container-executors.md`, `slurm.md`, `runtime-resources.md`,
  `preflight.md`, `provenance.md`, `reliability.md`, and `testing.md` likely
  need updates once behavior is confirmed.

Likely public surfaces and durable artifacts:

- Public or semi-public records for Apptainer/Singularity options such as image
  path or URI, bind mounts, workdir, selected environment, GPU flags, runtime
  command choice, and redacted command projection.
- Public or semi-public records for Apptainer build inputs and outputs:
  definition file path or explicit build source, output `.sif` path, build args,
  fakeroot/notest/reproducible/force/sandbox choices where selected, temporary
  directory/cache summaries, and redacted build command projection.
- Public or semi-public records for container build-service requests and
  results: requested local builder, input source, output SIF/image location,
  build status, build logs, worker metadata, provenance hash, and failure
  diagnostics.
- Shared container build records that can represent Docker image outputs and
  Apptainer SIF outputs from a reusable build spec: build target name, runtime
  kind, context/source, recipe source or generated recipe record, build args,
  cache policy, output reference, digest/hash when available, and redacted
  command/provenance.
- Runtime descriptor entries for `apptainer` and possibly `singularity`, plus a
  composition policy for SLURM plus Apptainer.
- CLI selection through existing `loom run` and preflight paths, likely using
  executor selection rather than a separate Apptainer command group.
- Generated SLURM dry-run artifacts whose scripts show Apptainer invocation and
  the inner Loom worker command.
- Executor metadata and provenance records for runtime name/version, image
  reference or path, cheap identity facts, bind summaries, environment key
  summaries, resource mapping, process exit code, and log paths.
- Stable preflight check IDs for command availability, image presence, bind
  sources, writable run/artifact roots, required environment variables, resource
  mapping, build environment readiness, and scheduler/container compatibility.

Structure rationale:

- This planning discussion should first lock the user-visible HPC workflow
  because the shape differs depending on whether the priority is direct
  Apptainer execution, SLURM dry-run script inspection, live SLURM submission,
  or release-grade examples.
- Capability triage needs to separate core Apptainer/Singularity execution from
  tempting HPC-specific expansion: full MPI orchestration, multi-node process
  coordination, site modules, automatic image conversion, registry/auth
  helpers, and security-sandbox language.
- The design pass must be stricter than an ordinary adapter stage because Stage
  18 sits across public config, executor lifecycle, SLURM script generation,
  resource mapping, artifact visibility, authority handoff, diagnostics, and
  future reliability policy.

Visible assumptions, risks, and constraints:

- Recommended default: optimize for per-stage Apptainer execution plus SLURM
  script composition that reuses the existing prepared-worker and submitted
  SLURM paths.
- Confirmed user direction: use Loom's existing machinery instead of inventing
  parallel runtime, scheduler, or lifecycle semantics.
- Confirmed user direction: make Apptainer support explicit and include SIF
  build/construction handling in Stage 18 planning.
- Confirmed user direction: include build-service support for container
  construction, local-only for now.
- Confirmed user direction: Docker and Apptainer should both include a build
  layer to dynamically build and run containers.
- Confirmed user direction: Loom should not require a container recipe file per
  stage; stages should reuse/select built container targets from shared
  build/run configuration.
- Confirmed user direction: Loom should submit requested resources through
  SLURM and should not own rank-level or MPI orchestration unless later proven
  necessary.
- Recommended default: treat `apptainer` as the primary runtime and
  `singularity` as a compatible command/alias unless the design pass finds a
  clear reason to expose separate semantics.
- Recommended default: keep default validation fake-command and cluster-free,
  with optional real Apptainer/SLURM acceptance only when explicitly enabled.
- Key risk: Stage 17 shared container records are not implemented in source in
  this checkout. Stage 18 must refresh its assumptions after Stage 17 lands.
- Key risk: path-parity mount assumptions may be harder on shared HPC
  filesystems and remote artifact backends. Planning must decide whether Stage
  18 still fails closed or introduces explicit path translation.
- Key risk: SLURM and Apptainer both have resource flags. Planning must avoid
  double-enforcement promises and make the scheduler/container ownership of
  CPU, memory, GPU, and wall time explicit.
- Key risk: SIF builds may need network access, registry credentials, temporary
  storage, fakeroot/user namespace support, or admin-controlled Apptainer
  configuration. Planning must keep those explicit and optional in default
  tests.
- Key risk: build-service support can easily become a registry, artifact
  transfer, credential, or daemon lifecycle feature. Stage 18 must keep the
  service contract local-only, narrow, and compatible with existing
  artifact/materialization and authority boundaries.
- Key risk: dynamic build support can accidentally become domain-specific
  environment management. Loom should provide generic build plumbing,
  provenance, caching, and selection, while project config owns actual package,
  OS, and dependency choices.
- Key risk: Stage 17 Docker planning currently defers image builds. The user
  selected the Stage 18 path: implement the shared generic container-build
  phase here, including Docker-specific build semantics where required, rather
  than treating Stage 17 plan amendment as the primary path.
- Constraint: no heavy runtime dependencies, no Python Apptainer/Singularity
  SDK dependency, no required real cluster/container runtime in default tests,
  and no site-specific module policy in core.

User clarification questions and resolved answers:

- User agreed that Stage 18 should use Loom's existing machinery.
- User clarified that Apptainer support should be explicit and that Stage 18
  must handle building/constructing Apptainer `.sif` files.
- User clarified that Stage 18 should include build-service support for
  container construction.
- User clarified that build service should be local-only for now.
- User clarified that Docker and Apptainer should both include a build layer to
  dynamically build and run containers.
- User clarified that Loom should not require a container recipe file per
  stage.
- User clarified that Stage 18 should implement a shared/generic
  container-build phase, adapting to Docker or Apptainer-specific semantics as
  required.
- User clarified that Loom should not own rank-level orchestration unless it is
  absolutely necessary; Loom should submit requested resources through SLURM.

## User Intent

Target audience:

- Confirmed: HPC pipeline authors and maintainers/operators who need
  inspectable local container-build records and SLURM-container jobs.

User-visible outcome:

- Confirmed direction: direct Apptainer/Singularity stage execution plus a
  shared Docker/Apptainer build layer, inspectable local build/build-service
  records, and SLURM plus Apptainer dry-run/live paths through existing `loom
  run` and preflight surfaces.

Success criteria:

- A user can configure one named container build target and reuse it across
  multiple stages.
- Loom can locally build or reuse Docker images and Apptainer SIFs with
  recorded build evidence.
- Apptainer can run prepared stage attempts through the normal worker/result
  contract.
- SLURM dry-run scripts can show Apptainer-wrapped Loom commands, and live
  submission reuses the existing v7 SLURM paths.
- Default validation uses fake/local builders and runners only; real
  Docker/Apptainer/SLURM coverage remains opt-in.

Non-goals:

- MPI/rank-level orchestration, multi-node topology decisions, site module
  policy, broad image conversion, registry/auth helpers, external/site build
  services, Kubernetes, Docker Compose, and security-sandbox claims.
- Project code still owns concrete package/environment choices inside
  Dockerfiles, Apptainer definition files, or other selected build sources.

Constraints:

- Keep Docker, Apptainer, and SLURM optional; default imports, CLI help,
  unrelated preflight, and default tests must not require real runtimes,
  clusters, images, registries, or network access.
- Use fake-command/fake-service validation by default, with optional real
  runtime smoke checks.
- Preserve existing worker, SLURM, run-store, artifact, provenance, diagnostics,
  and authority boundaries.
- Persist redacted build, command, environment, and runtime metadata only.
- Keep `loom` domain-neutral; do not generate domain-specific container
  recipes.

## Functionality, Behavior, Code Structure, And Usage Readback

User-approved functionality summary:

- Stage 18 implements HPC container execution for Loom by building or reusing a
  configured container output, running prepared stage workers inside
  Apptainer/Singularity, and composing that execution with existing SLURM
  dry-run/live submission behavior.
- Stage 18 does not implement a new scheduler, MPI launcher, registry,
  external build farm, site module system, image publisher, or security sandbox.
- The durable user behavior is more important than the illustrative field names
  below. The implementation plan may refine exact schema names, but must
  preserve named reusable build targets, local foreground build/reuse, direct
  Apptainer execution, SLURM command wrapping, clean environment defaults,
  explicit output refs, and fake/default-offline validation.

Expected usage flow:

1. A user defines one or more named container build targets at run/profile
   scope.
2. A stage inherits or selects a named target instead of carrying its own
   per-stage Dockerfile or Apptainer definition.
3. Loom resolves the target before execution, builds it locally when policy
   requires, or reuses the existing output when policy allows.
4. Loom records redacted build request/result evidence in run-local metadata.
5. The selected executor runs the normal Loom prepared worker command from the
   resolved Docker image ref or Apptainer SIF path.
6. Direct Apptainer execution returns through the normal worker/result contract.
7. SLURM plus Apptainer dry-run/live paths reuse existing SLURM manifests,
   scripts, status, cancel, resources, and fake command-runner behavior.

Illustrative runtime/profile shape:

```yaml
profiles:
  hpc:
    executor: slurm-afterok

    container_build:
      targets:
        analysis-env:
          runtime: apptainer
          policy: if_stale
          source:
            type: definition_file
            path: containers/analysis.def
          output:
            type: sif
            path: .loom/containers/analysis-env.sif

    container:
      target: analysis-env
      workdir: /workspace
      mounts:
        - source: .
          target: /workspace
          mode: ro
        - source: runs
          target: /workspace/runs
          mode: rw
```

Illustrative local SIF build behavior:

```bash
apptainer build .loom/containers/analysis-env.sif containers/analysis.def
```

The build result records the target name, runtime, output ref, build policy,
redacted command, selected builder identity, status, log references, and failure
diagnostics when applicable. Build evidence is not a committed stage output by
default; the adapter output ref is the reusable Docker image identity or
Apptainer SIF path.

Illustrative direct Apptainer worker command:

```bash
apptainer exec \
  --cleanenv \
  --bind /host/project:/workspace:ro \
  --bind /host/runs:/workspace/runs:rw \
  --pwd /workspace \
  .loom/containers/analysis-env.sif \
  python -c 'from loom.cli.main import main; raise SystemExit(main())' \
    stage run \
    --run-uri /workspace/runs/run-001 \
    --stage train \
    --attempt 1
```

Illustrative SLURM plus Apptainer dry-run script shape:

```bash
#!/usr/bin/env bash
#SBATCH --job-name=loom-train
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00

set -euo pipefail

apptainer exec \
  --cleanenv \
  --nv \
  --bind /shared/project:/workspace:ro \
  --bind /shared/runs:/workspace/runs:rw \
  --pwd /workspace \
  /shared/loom/images/analysis-env.sif \
  loom stage run --run-uri /workspace/runs/run-001 --stage train --attempt 1
```

SLURM scripts must contain execution commands against resolved images/SIFs. They
must not hide Docker or Apptainer build commands inside submitted batch scripts.
Build failures remain local/controller-side failures before script rendering or
live `sbatch`.

Expected code structure:

- `loom.pipeline.executors.container` owns shared import-light build records,
  target/source/policy/request/result/output-ref models, build key helpers,
  redaction helpers, and the local build-service protocol/fake implementation.
- `loom.pipeline.executors.apptainer` owns Apptainer/Singularity options,
  `apptainer build` command construction, `apptainer exec` command
  construction, command runner protocol, direct executor behavior, and
  Apptainer-specific provenance.
- Docker build support adapts the shared build request/result contract to
  Docker-specific build semantics without moving Docker runtime behavior into
  shared records.
- `loom.pipeline.executors.slurm` remains the scheduler authority and gains only
  the composition point needed to wrap existing worker/continuation argv in
  resolved Apptainer execution.
- `loom.pipeline.runtime` owns descriptor registration and adapter namespace
  validation for `container`, `container_build`, `docker`, `apptainer`,
  `singularity`, and `slurm`.
- `loom.diagnostics.preflight` owns selected-executor and selected-build-target
  readiness checks with stable IDs, cheap defaults, and opt-in real runtime or
  cluster smoke.

Resource and environment behavior:

- In SLURM modes, SLURM owns scheduler allocation and enforcement for nodes,
  tasks, CPU, memory, wall time, scheduler status, and cancellation.
- Apptainer owns the container runtime shape: image/SIF, bind mounts, working
  directory, clean environment, explicit environment projection, and device
  exposure flags such as `--nv` or `--rocm`.
- Loom does not own MPI rank orchestration, `mpirun`/`srun` policy, PMI/PMIx
  compatibility, or site module setup in Stage 18.
- Apptainer execution defaults to clean environment behavior plus explicit
  environment projection. Broader host inheritance requires explicit config.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- User confirmed Stage 18 should use Loom's existing machinery.
- User confirmed explicit Apptainer support.
- User confirmed `.sif` build/construction handling must be included.
- User confirmed build-service support for container construction should be
  included, local-only for now.
- User confirmed Docker and Apptainer need a shared dynamic build-and-run layer.
- User confirmed Loom should not require per-stage container recipe files.
- User confirmed Stage 18 should own the shared/generic container-build phase,
  with runtime-specific adapter semantics where required.
- User agreed to the build model where runtime/profile configuration names
  reusable build targets, the local build service builds or reuses the target,
  and Docker or Apptainer executors run stages from the resolved image/SIF.
- User agreed that exact YAML field names are design-pass details, while the
  behavior is build once or reuse across stages rather than per-stage recipe
  files.
- User confirmed the primary target audience is HPC pipeline authors and
  maintainers/operators.
- User confirmed the planning priority is build-once/reuse-across-stages
  container targets plus Apptainer-on-SLURM parity, while preserving Stage 19
  reliability compatibility.
- User confirmed Loom should not own rank-level orchestration unless absolutely
  necessary. Loom should submit requested resources through SLURM.

Intent discovery locked decisions:

- Success criteria are confirmed:
  - one named build target can be reused across multiple stages;
  - Docker images and Apptainer SIFs can be locally built or reused with build
    evidence;
  - Apptainer uses the prepared worker/result contract;
  - SLURM dry-run/live paths reuse existing v7 machinery;
  - default validation is fake/local, with real runtime coverage opt-in.
- Non-goals and constraints follow the roadmap and confirmed local-only build
  service/rank-orchestration boundaries.
- User confirmed there are no extra hard operational constraints beyond
  optional runtimes, fake/local default validation, redacted metadata, existing
  Loom boundaries, and domain neutrality.

Capability triage and candidate-functional-requirement readback:

- Confirmed capability sort:
  - Include shared Docker/Apptainer dynamic build layer, named reusable build
    targets, local-only build service, explicit Apptainer SIF build/construction,
    direct Apptainer/Singularity execution, runtime detection, bind/workdir and
    local run/artifact-root validation, selected environment handoff and
    redaction, image/runtime/build provenance, SLURM plus Apptainer dry-run/live
    composition, resource ownership diagnostics, selected-executor preflight,
    and fake-command/fake-service tests.
  - Apptainer build sources include both user-authored definition files and
    explicit local/URI sources accepted by `apptainer build`.
  - Defer external/site build-service adapters, registry/auth helpers, broad
    automatic image conversion, MPI/rank-level orchestration, site module policy,
    Kubernetes, Docker Compose, and security-sandbox claims.

Functionality-agreement readback:

- Functionality agreement queue is resolved with no unresolved high-impact
  requirement blockers:
  - Stage 18 optimizes for build-once/reuse-across-stages container targets
    plus Apptainer-on-SLURM parity while preserving Stage 19 reliability
    compatibility.
  - Apptainer SIF builds include user-authored definition files and explicit
    local/URI sources accepted by `apptainer build`.
  - Shared Docker/Apptainer build targets are implemented in Stage 18.
  - Build service is local-only.
  - SLURM owns requested resources; Loom does not own rank orchestration.
  - Named build targets default to `if_stale`, with explicit `always` and
    `never` policies.
  - Local build service is foreground/local only, with fakeable runners and
    recorded request/result evidence.

Functionality and behavior confirmation readback:

- Behavior baseline is confirmed:
  - Users configure reusable named Docker/Apptainer build targets once at
    run/profile scope; stages inherit or select those targets.
  - Foreground/local build service builds or reuses targets and records
    request/result evidence.
  - Build policy defaults to `if_stale`, with explicit `always` and `never`
    policies.
  - Apptainer SIF builds support user-authored definition files and explicit
    local/URI sources accepted by `apptainer build`.
  - Apptainer execution uses the prepared worker/result contract.
  - SLURM plus Apptainer dry-run/live paths reuse existing v7 SLURM machinery.
  - Missing build inputs, unavailable local build/runtime commands, invalid
    outputs, executor failures, and scheduler/container incompatibility produce
    explicit diagnostics or result records.
  - External/site build services, registry/auth helpers, implicit conversion,
    background build pools, whole-controller-in-container mode, per-stage
    required recipes, rank-level orchestration, and security-sandbox claims are
    out of scope.

Design-agreement follow-up:

- Design agreement resumed from the checkpoint on 2026-05-16.
- Proposed implementation shape and design-agreement queue have been drafted.
- Clear repo-supported decisions are recorded without asking the user to
  reconfirm them.
- Stage 18 carries forward Stage 17's expected shared `container` namespace and
  executor-owned shared records, but records a refresh trigger because Stage 17
  source has not landed in this checkout.
- Design-safety review passed with no high-impact `needs discussion` or
  `blocked` design decisions.

Examples, validation, phase-shaping, and final-confirmation readback:

- Examples and validation strategy are confirmed.
- Phase shaping is confirmed with five phases: shared build contracts/config
  semantics; local build service and runtime builders; direct
  Apptainer/Singularity execution; SLURM plus Apptainer composition; preflight,
  docs, and opt-in smoke coverage.
- User reviewed the concrete functionality, behavior, code-structure, and usage
  explanation and confirmed it is good.
- User asked to ensure this planning document reflects that explanation and to
  run the remaining workflow steps to approve implementation-plan drafting.
- The Stage 18 planning artifact is accepted as the source for
  implementation-plan drafting.
- The Stage 18 implementation-plan draft was created after refreshing current
  source assumptions. The source refresh found Stage 17 Docker/shared-container
  modules still absent in this checkout, so the draft records that as an
  accepted risk and Phase 1 execution-planning prerequisite.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Existing Loom machinery, explicit Apptainer support, Stage 18-owned shared/generic container-build phase, `.sif` build/construction handling, local-only build-service need, no per-stage container recipe requirement, build-once/reuse-across-stages behavior, primary audience, planning priority, and SLURM resource-submission boundary are confirmed. | Runtime/profile config names reusable build targets; local build service builds or reuses the target; Docker/Apptainer executors run from the resolved image/SIF; exact field names are design details; fake-command default validation; no Loom-owned rank orchestration. | Exact build-source scope remains for functionality agreement. | Move to intent discovery. |
| Intent discovery | Success criteria, non-goals, constraints, and no-extra-constraints response confirmed. | Local build evidence, Apptainer execution, SLURM dry-run/live reuse, cheap default validation, and Stage 19-compatible facts. | None. | Move to capability triage. |
| Capability triage and candidate functional requirements | Capability sort confirmed, including Apptainer definition files and explicit local/URI sources. | Include shared Docker/Apptainer build layer, local build service, Apptainer execution, SLURM composition, diagnostics, provenance, resource ownership, and fake tests; defer broad orchestration/auth/site-service work. | None. | Move to functionality agreement review. |
| Functionality agreement review | Confirmed. | All high-impact requirement defaults are resolved. | None. | Move to functionality and behavior confirmation. |
| Functionality and behavior confirmation | Confirmed. | Build target selection/reuse, foreground/local build execution, Apptainer execution, SLURM composition, preflight, provenance, failure behavior, and deferrals are locked. | None. | Record checkpoint. |
| Context compaction/reset checkpoint | Completed. | Resume design review from this artifact without reopening functionality unless explicitly requested. | None. | Design-safety review completed; next confirm examples and validation strategy. |
| Design agreement review | Proposed implementation shape and DAQ-1 through DAQ-12 recorded. Stage 18 extends Stage 17's narrow shared container execution records with a separate shared `container_build` namespace, adds Apptainer/Singularity adapter behavior, and composes SLURM by wrapping existing generated worker commands. | Executor-owned shared records; runtime/profile adapter namespaces; `apptainer` primary with `singularity` compatibility alias; path-parity fail-closed; foreground local build service; fake-command/default-offline validation. | None. | Design-safety review completed. |
| Design safety review | Passed. DAQ-1 through DAQ-11 remain recorded recommendations; DAQ-12 is upheld as auto-approved after adding cheap-check obligations. Review added guardrails for `container_build` merge semantics, explicit build output placement, submit-side SLURM build ordering, and Apptainer clean environment defaults. | Existing adapter namespace replacement semantics apply unless a future typed merge model is explicitly designed; build evidence is run-local but build outputs use explicit adapter output refs; SLURM scripts run built images/SIFs and do not hide builds; Apptainer uses explicit/clean env by default. | None. | Confirm examples and validation strategy. |
| Examples and validation strategy | Confirmed examples cover direct Apptainer execution, SIF build, local build service, shared build/reuse targets, namespace replacement behavior, SLURM dry-run/live composition, clean-env command construction, and selected preflight. | Default evidence uses fake builders/runners, deterministic script rendering, stable diagnostics, and docs snippets; real runtime/cluster smoke remains opt-in. | None. | Phase shaping completed. |
| Phase shaping | Five-phase implementation shape recorded: shared build contracts/config semantics; local build service and runtime builders; direct Apptainer/Singularity execution; SLURM plus Apptainer composition; preflight/docs/optional smoke coverage. | Public contracts and config semantics land before runtime behavior; scheduler composition waits for direct execution and build outputs; preflight/docs finalize after behavior is stable. | None. | Final planning readiness check. |
| Implementation readiness | Roadmap, requirements, design, design safety, examples, validation strategy, phase shaping, and user-approved functionality/behavior/code-structure readback are recorded with no unresolved `needs discussion` or `blocked` decisions. | Implementation-plan drafting refreshed current Stage 17 source assumptions and preserved accepted design-safety guardrails. | None. | Implementation-plan quality gate. |
| Handoff | Planning handoff completed. The Stage 18 planning artifact was accepted as the primary source for implementation-plan drafting. | Use the drafted implementation plan next; do not draft phases before the implementation-plan quality gate passes. | None. | Implementation-plan quality gate. |
| Final planning confirmation | User confirmed the explanation is good, asked to ensure the planning document reflects it, and approved remaining workflow steps for implementation-plan drafting. | Draft from this confirmed artifact; refresh Stage 17 source again before Phase 1 execution planning if prerequisite work lands. | None. | Implementation-plan quality gate. |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Standalone Apptainer/Singularity prepared-stage execution | include | Directly required by the roadmap and exit criteria. | Reuse the same worker contract as Docker. |
| Explicit Apptainer SIF build/construction | include; user confirmed | User stated Stage 18 needs to handle building/constructing `.sif` files. | Include user-authored definition files and explicit local/URI sources accepted by `apptainer build`; defer implicit conversion and auth helpers. |
| Container build-service support | include; user confirmed local-only | User stated Stage 18 needs build-service support for the container and then clarified local-only for now. | Current Apptainer docs do not support old remote-build behavior; external or site build-service adapters are deferred. |
| Shared Docker/Apptainer dynamic build layer | include; user confirmed | User stated Docker and Apptainer should include a build layer to dynamically build and run the container. | Implement in Stage 18 as a shared/generic container-build phase with runtime-specific adapters. |
| Named reusable build targets instead of per-stage recipe files | include; user confirmed | User stated users should not have to make a container file per stage. | Recommended shape: project/run/profile build specs produce named outputs; stages select targets or inherit defaults. |
| Runtime command detection for `apptainer` and `singularity` | include | Required by roadmap and feature docs. | Design pass must settle alias versus separate executor semantics. |
| Bind mount, workdir, and run/artifact-root validation | include | Required for correctness on local and HPC filesystems. | Must revisit path-parity assumptions after Stage 17 lands. |
| Selected environment handoff and redaction | include | Required by container feature docs and trust boundary. | Do not pass or persist full host environment by default. |
| Image/runtime provenance | include | Required by roadmap and provenance feature docs. | Cheap identity only by default; no pull/conversion/registry requirement. |
| Resource mapping with SLURM/container ownership made explicit | include | Required by roadmap and critical for HPC correctness. | Avoid double-enforcement claims for CPU, memory, GPU, and wall time. |
| SLURM plus Apptainer dry-run script composition | include | Required by exit criteria and useful for reviewability. | Preserve deterministic scripts/manifests. |
| Live SLURM plus Apptainer using v7 submission paths | include | Required by exit criteria. | Reuse submitted-operation records and status/cancel behavior. |
| Selected-executor preflight for Apptainer and scheduler/container compatibility | include | Required by roadmap and feature docs. | Default checks stay cheap and no-runtime for unrelated executors. |
| Fake-command tests for command/script/failure behavior | include | Required by roadmap and testing feature docs. | Optional real runtime/cluster tests stay opt-in. |
| MPI orchestration and rank-level coordination | defer unless absolutely necessary | User confirmed Loom should not own rank-level orchestration and should submit requested resources through SLURM. | Stage 18 may render configured `mpirun`/`srun apptainer exec` commands if supplied, but should not decide MPI rank topology or compatibility policy. |
| Site-specific module loading | defer | Explicitly deferred by roadmap and too site-dependent for core. | Core may allow users to configure script preludes without owning module policy. |
| Automatic image conversion or registry authentication | defer for broad helpers; reopen only for explicit user-authored build sources | Roadmap defers these broadly, but user confirmed `.sif` build support. | Proposed boundary: support explicit `apptainer build` from configured local def files or configured source URIs; do not add auth helpers or implicit conversion. |
| External or site build-service adapters | defer | User clarified local-only for now. | Revisit after local build-service records and semantics are stable. |
| Container security sandbox guarantees | out of scope | Explicitly deferred by roadmap and feature docs require trust clarity. | Authored configs remain trusted project code. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Confirm Stage 18 optimizes for build-once/reuse-across-stages container targets plus Apptainer-on-SLURM parity rather than broader HPC orchestration. | none | 1 | Yes; keep MPI, multi-node, modules, image conversion, registry auth, external build services, and sandbox claims deferred while preserving Stage 19 reliability compatibility. | This sets the boundary for all functional requirements. | User confirmed the planning priority during roadmap framing. | confirmed |
| FRQ-2 | Confirm the `.sif` build support boundary. | FRQ-1 | 2 | Include explicit `apptainer build` planning/execution from user-authored definition files and explicit local/URI sources with recorded outputs; defer registry-auth helpers, implicit image conversion, and site-specific build services. | Build support changes Stage 18 from runtime-only to runtime plus image-construction provenance. | User confirmed this during capability triage. | confirmed |
| FRQ-3 | Confirm the shared Docker/Apptainer build layer boundary. | FRQ-2 | 3 | Include named reusable build specs and build outputs for Docker images and Apptainer SIFs; stages inherit/select targets instead of owning recipe files; implement the generic phase in Stage 18. | This changes Stage 18 into a cross-runtime build layer plus Apptainer/HPC composition stage. | User confirmed the direction; design must lock exact public config and phase boundaries. | confirmed |
| FRQ-4 | Confirm the container build-service boundary. | FRQ-3 | 4 | Include a narrow local-only build-service contract that can run/track explicit build requests; do not assume Apptainer remote-build support, configured site builders, or registry/auth service behavior. | Build-service support affects authority, artifact, logs, credentials, and validation surfaces. | User requested build service and confirmed local-only for now. | confirmed |
| FRQ-5 | Confirm Slurm owns requested resources and Loom does not own rank orchestration. | FRQ-1 | 5 | Yes; Loom maps/submits requested resources to SLURM and records the generated launch command, while MPI/rank semantics stay user/site-owned unless a later blocker proves otherwise. | Prevents Stage 18 from becoming an MPI launcher or multi-node orchestration framework. | User confirmed this direction. | confirmed |
| FRQ-6 | Confirm build policy defaults for named build targets. | FRQ-3, FRQ-4 | 6 | Default to explicit `if_stale`/reuse behavior with recorded build keys; support `always` and `never` policies; do not rebuild blindly before every stage. | Build policy affects user-visible run behavior, reproducibility, runtime cost, and cache correctness. | User agreed to this default. | confirmed |
| FRQ-7 | Confirm local build-service execution mode. | FRQ-4, FRQ-6 | 7 | Start with foreground/local build orchestration with fakeable runners and recorded results; defer daemonized build pools. | This keeps Stage 18 local and reviewable while preserving a service/worker contract for future expansion. | User confirmed foreground/local only. | confirmed |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Direct Apptainer/Singularity stage execution | none | Execute prepared stage attempts through `apptainer exec` or compatible `singularity` command. | Brings HPC-compatible container runtime support to Loom. | Standalone per-stage execution only; not whole-controller or multi-node orchestration. | Users select an Apptainer/Singularity executor and run ordinary Loom stages. | Executor builds command, invokes fakeable runner, reads worker result, and returns normal stage result. | Standalone Apptainer execution | Fake-runner executor tests and command builder tests. | confirmed |
| FR-2 | SLURM plus Apptainer composition | FR-1 | Generate and submit SLURM scripts whose job commands run Loom worker commands inside Apptainer. | Matches common HPC deployment path without replacing SLURM state handling. | Dry-run script generation and live submission through v7 paths. | Users inspect dry-run scripts and submit live jobs with containerized stage commands. | SLURM manifests/status/cancel remain authoritative scheduler records. | SLURM-container execution | Script rendering tests, manifest tests, fake live submission tests. | confirmed |
| FR-3 | Apptainer SIF build/construction | none | Build configured `.sif` outputs through explicit `apptainer build` command records. | Users need reproducible image construction, not only runtime invocation of an opaque image. | User-authored definition files and explicit local/URI build sources; no implicit registry auth, site build service, or automatic conversion. | Users can inspect build command, input source, output SIF path, and build result/provenance. | Loom records build inputs, command projection, output path, checks, and failures through fakeable command runner. | Image construction provenance | Fake build-runner tests, preflight tests, and docs examples. | confirmed by user |
| FR-7 | Build policy and reuse | FR-6 | Apply explicit build policy for named build targets so Loom can reuse outputs or rebuild predictably. | Prevents per-stage rebuilds and makes build evidence reproducible. | `if_stale` default with `always` and `never` explicit policies; exact field names remain design detail. | Users can choose whether Loom rebuilds, reuses, or fails if output is missing/stale. | Loom computes recorded build keys/fingerprints and persists reuse/build decisions. | Build reuse correctness | Unit tests for keying, policy decisions, stale detection, and diagnostics. | confirmed by user |
| FR-8 | Local build-service execution mode | FR-4, FR-7 | Run local build requests through a foreground/fakeable local build service/worker contract. | Keeps Stage 18 local-only and testable while preserving an explicit build-service abstraction. | No daemonized build pool or external service. | Users see local build progress/result records in the run evidence. | Loom executes or fakes local build commands and persists request/result records. | Local build service | Fake service tests and optional real local smoke. | confirmed by user |
| FR-4 | Local container build service | FR-3 | Provide an explicit local service/worker contract to build and expose images/SIFs for later execution/submission. | Users need a controlled local build path without depending on unsupported Apptainer remote-build behavior. | Local Loom-managed build worker only; external/site build-service adapters, registry/auth service, and implicit conversion are deferred. | Users can request, inspect, and reference a locally built image/SIF as an execution input. | Loom records build request/result state, local worker identity, output location, logs, and failures while preserving artifact boundaries. | Build-service integration | Fake service tests, contract tests, preflight checks, optional real local build smoke. | confirmed by user |
| FR-5 | SLURM resource submission without rank orchestration | FR-2 | Submit requested resources through existing SLURM mappings and render configured container launch commands without Loom deciding MPI rank topology. | Keeps Loom aligned with its executor role and avoids owning site-specific MPI behavior. | Resource requests, SBATCH directives, configured `mpirun`/`srun` or direct command templates only. | Users see generated Slurm scripts and resources; rank semantics remain explicit user/site config. | SLURM resources and manifests stay authoritative; Loom records launch command and scheduler facts. | Slurm-container resource submission | Script/resource mapping tests and docs examples. | confirmed by user |
| FR-6 | Shared dynamic build-and-run layer for Docker and Apptainer | FR-3, FR-4 | Define reusable named build specs and build outputs that Docker and Apptainer executors can build then run. | Users should not have to prebuild images manually or write a recipe per stage. | Project/run/profile-level build specs, build policies, cache/fingerprint records, and stage target selection; no per-stage required container files; Stage 18 owns the generic phase. | Users configure a default or named container build target once and run many stages from it. | Loom builds or reuses the target according to policy, persists build evidence, then passes the output image/SIF into the executor. Runtime-specific adapters handle Docker and Apptainer details. | Cross-runtime build reuse | Shared build record tests, Docker/Apptainer fake build tests, config/profile tests. | confirmed by user |

## Behavior Baseline

Included functionality:

- Shared Docker/Apptainer dynamic build-and-run layer with named reusable build
  targets.
- Foreground/local build-service execution with fakeable runners and recorded
  request/result evidence.
- Apptainer SIF build/construction from user-authored definition files and
  explicit local/URI sources accepted by `apptainer build`.
- Direct Apptainer/Singularity prepared-stage execution.
- Runtime detection for `apptainer` and compatible `singularity`.
- Bind, workdir, local run-directory, and local artifact-root validation.
- Explicit environment handoff and redacted persisted metadata.
- Image, runtime, build, scheduler, and command provenance.
- SLURM plus Apptainer dry-run script composition and live submission through
  existing v7 SLURM paths.
- Resource mapping with SLURM/container ownership made explicit.
- Selected-executor preflight, fake-command tests, fake-service tests, and
  optional real runtime smoke coverage.

User-visible behavior:

- Users configure named container build targets once at run/profile scope, then
  stages inherit or select those targets. The local build service builds or
  reuses the target according to policy and passes the resolved Docker image or
  Apptainer SIF to the selected executor.

Default behavior:

- Build targets are reusable across stages. Exact config field names remain a
  design-pass detail, but per-stage recipe files are not required.
- Named build targets default to `if_stale`: reuse recorded outputs when the
  build key is valid and rebuild when relevant inputs changed. `always` and
  `never` are explicit policy options.

Failure behavior and diagnostics:

- Build failures, missing build inputs, missing local Docker/Apptainer build
  commands, invalid output references, and executor failures should be recorded
  as explicit Loom diagnostics and build/executor result records.

Explicit deferrals:

- External/site build-service adapters, registry/auth helpers, implicit image
  conversion, rank-level MPI orchestration, site-specific module policy,
  Kubernetes, Docker Compose, and security-sandbox claims.

Out-of-scope behavior:

- Per-stage required container recipe files.
- Whole-controller-in-container execution.
- Daemonized build pools or background build queues.
- External build service integration.
- Registry login, credential helpers, or image publishing.
- MPI rank topology, node layout, PMI/PMIx compatibility policy, or launcher
  selection beyond rendering configured commands.

Context compaction/reset checkpoint:

- Checkpoint status: completed
- Notes path: `docs/roadmap/stage-18/planning.md`
- Resume instruction: reload `docs/roadmap/stage-18/planning.md`,
  `.codex/workflows/roadmap-stage-planning.md`, and
  `.codex/prompts/roadmap-stage-design-agreement.md`; treat roadmap framing,
  intent, capability triage, functionality agreement, and behavior baseline as
  confirmed unless the user explicitly reopens them; start the design-agreement
  review by drafting the proposed implementation shape and design-agreement
  queue.
- Functionality and behavior reopened after checkpoint: no

## Proposed Implementation Shape

Likely modules or packages:

- Reuse the Stage 17 planned `loom.pipeline.executors.containers` package for
  import-light shared container execution records and add shared build records
  under the same executor-owned boundary, likely as
  `loom.pipeline.executors.containers.builds` or a sibling module inside the
  `containers` package.
- Add Apptainer/Singularity-specific command construction, option parsing,
  command-runner protocols, SIF build helpers, and direct executor behavior
  under `loom.pipeline.executors.apptainer`.
- Extend `loom.pipeline.executors.docker` only where Stage 18's shared build
  layer needs Docker-specific build adapter behavior. Do not move Docker
  execution semantics into shared records.
- Extend `loom.pipeline.executors.slurm` by adding an Apptainer command-wrapping
  composition point around existing generated `SlurmCommandArgv` worker
  commands. Keep planning, rendering, live submission, manifests, status, and
  cancellation on the existing SLURM paths.
- Extend `loom.pipeline.runtime.capabilities` with descriptors/namespace claims
  for `apptainer`, `singularity`, Docker build support, Apptainer build support,
  and SLURM plus Apptainer composition. Runtime descriptors stay import-light.
- Extend `loom.diagnostics.preflight` and `loom.diagnostics.models` with stable
  selected-executor checks for container build targets, Apptainer/Singularity,
  SIF build readiness, mounts, writable run/artifact roots, and
  scheduler/container compatibility.
- Update docs and examples in `docs/features/container-executors.md`,
  `docs/features/slurm.md`, `docs/features/runtime-resources.md`,
  `docs/features/preflight.md`, and `docs/features/provenance.md` after design
  safety validates the shape.

Likely public classes, functions, or protocols:

- Shared container-build records:
  `ContainerBuildTarget`, `ContainerBuildSource`, `ContainerBuildPolicy`,
  `ContainerBuildRequest`, `ContainerBuildResult`, `ContainerBuildOutputRef`,
  and redacted build metadata helpers. Exact names are implementation-plan
  details, but the contract should be plain-data, schema-versioned, and
  import-light.
- Local build service contract:
  a narrow `ContainerBuildService` or `ContainerBuilder` protocol with a
  foreground local implementation and fake implementation. It accepts explicit
  build requests, returns build/reuse/failure results, and never assumes a
  daemonized queue or external/site builder.
- Runtime-specific builder protocols:
  Docker and Apptainer builders translate a shared build request into
  runtime-specific argv, validate runtime-specific options, and normalize
  command results. The shared layer should not import Docker or Apptainer
  subprocess behavior.
- Apptainer command contracts:
  `ApptainerOptions`, `ApptainerBuildOptions`, `ApptainerCommandRunner`,
  `ApptainerCommandResult`, command builders for `apptainer exec` and
  `apptainer build`, and `ApptainerExecutor`.
- Compatibility surface:
  `singularity` resolves to the same Apptainer adapter semantics while
  preserving the selected command name in metadata.
- SLURM composition helpers:
  a function or value object that wraps an existing `SlurmCommandArgv` in an
  Apptainer exec argv without changing the submitted-operation manifest model.

Likely internal helpers:

- Build-key/fingerprint helpers that hash explicit source descriptors, local
  recipe file content summaries, selected build args/options, output path, and
  adapter kind for `if_stale` decisions. Network-backed URI contents are not
  fetched just to compute default keys.
- Path validation helpers for path-parity run directories, artifact roots,
  bind source existence, absolute container targets, mode validation, and
  writable local roots.
- Redaction helpers for argv, environment, build args, adapter payloads,
  command outputs, and diagnostics.
- Command availability/version probes using `shutil.which` and cheap
  subprocess calls only when the selected executor or selected build target
  requires them.
- Output validation for Apptainer SIF builds: after a successful build command,
  the configured output must exist, be a file, and have a recorded path/size/hash
  summary when locally available.

Data flow:

- Runtime/profile config supplies shared execution options in `container`,
  shared build targets in `container_build`, runtime-specific options in
  `docker` or `apptainer`, and scheduler options in `slurm`.
- `container_build` uses the existing adapter-namespace merge contract unless
  a later stage explicitly introduces typed namespace-local merging: a higher
  precedence source replaces the whole `container_build` payload rather than
  merging individual build targets. Stage 18 examples and validation should
  make this complete-namespace override behavior visible.
- Before a containerized stage attempt runs, the selected executor or SLURM
  planning path resolves the selected container build target, invokes the local
  foreground build service only when policy requires it, records the
  build/reuse result, and passes a resolved Docker image reference or
  Apptainer SIF path/URI to command construction.
- For SLURM plus Apptainer, build resolution happens on the controller/submit
  side before dry-run script rendering or live `sbatch` submission. Generated
  SLURM scripts run `apptainer exec` against a resolved image/SIF; they do not
  hide `apptainer build` or Docker build steps inside the batch script.
- Direct Apptainer execution mirrors `SubprocessExecutor`: build the durable
  worker command, wrap it in `apptainer exec` or compatible `singularity exec`,
  run through an injectable command runner, read the worker result from the
  run store, and normalize process/worker conflicts into `StageExecutionResult`.
- SLURM plus Apptainer keeps the existing single-job and afterok modes. The
  SLURM planner builds the same Loom continuation/stage-job command argv, then
  wraps that argv in Apptainer before rendering scripts and manifests. Live
  submission still calls existing `sbatch`, status, and cancellation paths.
- Build results, command results, image/SIF identity facts, scheduler facts,
  and selected environment summaries are persisted as redacted executor,
  submitted-operation, generated-artifact, or provenance metadata. They do not
  become semantic stage fingerprints by default.
- Build evidence is run-local by default, but actual build outputs use explicit
  adapter output references: a Docker output may be a local image ref/tag or
  digest-like identity, and an Apptainer output may be a configured SIF path.
  Stage 18 should not invent a global cross-run image cache or silently store
  build outputs as committed stage outputs.

Dependency direction:

- Shared container/build value objects depend only on serialization,
  timestamps, errors, and executor-local helpers. They must not import Docker,
  Apptainer, SLURM live operations, diagnostics, CLI, config composition,
  plugin discovery, or downstream project code.
- Docker and Apptainer adapters consume shared container/build records and the
  existing worker command contract; they do not own DAG planning, run-store
  finalization, artifact indexes, resume policy, or cleanup.
- SLURM composition consumes Apptainer command-building helpers or neutral argv
  wrappers; Apptainer direct execution must not import SLURM.
- Diagnostics consume safe summaries and adapter validation helpers, not raw
  runtime command execution or backend SDKs.
- CLI remains a thin selector over existing `loom run`, `loom preflight`, and
  submitted-operation commands; no Docker/Apptainer build command group is
  introduced in Stage 18.

Extension points and flexibility boundaries:

- Build service is deliberately local-only in Stage 18, but the
  request/result protocol should leave a future extension point for external or
  site build services without changing build target config or result records.
- Build targets are named and reusable. Stages select a target or inherit a
  default; they do not carry one recipe file per stage.
- Shared `container_build` records cover target identity, adapter kind, source,
  recipe/context descriptor, build args, cache/policy, output reference, build
  key, and redacted evidence. Dockerfile syntax, buildx options, Apptainer
  definition sections, fakeroot, sandbox, and SIF flags stay runtime-specific.
- Path translation is not introduced in Stage 18. Path parity remains the
  default with explicit fail-closed diagnostics for non-local, non-mountable,
  or mismatched paths. Revisit when remote stores or site deployments require a
  path-mapping protocol.
- SLURM owns requested resources. Apptainer options may expose runtime access
  flags such as GPU `--nv`/`--rocm`, but CPU, memory, node count, task count,
  and wall time remain scheduler-owned in SLURM modes.
- Apptainer execution should default to an explicit/clean environment handoff,
  using Apptainer's clean-environment behavior and explicit env projection
  unless config opts into a broader inherited environment. This preserves the
  confirmed redaction and reproducibility boundary.
- MPI, rank topology, launcher choice, PMI/PMIx compatibility, and multi-node
  container coordination stay user/site-owned. Loom may render configured
  launch commands and record them but does not infer ranks.

Generic interface, adapter, or protocol shape:

- Public adapter namespaces should be:
  - `container` for generic execution-time image/workdir/mount/environment
    selection and selected build-target reference;
  - `container_build` for named reusable build target definitions, policies,
    and local build-service options;
  - `docker` for Docker runtime/build semantics;
  - `apptainer` for Apptainer/Singularity runtime/build semantics;
  - `slurm` for scheduler options and script preludes.
- Executor descriptors should claim the namespaces they can consume without
  importing concrete command runners. Docker claims `container`,
  `container_build`, and `docker`; Apptainer/Singularity claims `container`,
  `container_build`, and `apptainer`; SLURM claims `slurm` and, for Stage 18
  composition, the Apptainer/container namespaces it can render into scripts.
- Command runner protocols remain runtime-specific for Stage 18. A universal
  command-runner abstraction is deferred until Docker, Apptainer, and SLURM
  duplication proves a stable shared primitive.
- Build request/result records are the reusable protocol; runtime-specific
  builders adapt them to Docker or Apptainer argv.

Future-roadmap impact:

- Stage 19 can consume build results, process facts, scheduler facts,
  container runtime facts, timeout-capability facts, and failure categories
  without backend-specific retry policy in Stage 18.
- Stage 20 can project committed build/run/submission facts into runtime
  events and observe-only sinks because records stay plain-data and redacted.
- Stage 21 can use generated logs, build outputs, staging/materialization facts,
  and local path summaries for cleanup without treating container build outputs
  as authority truth.
- Future remote artifact-store work can either mount/materialize host-visible
  payloads explicitly or fail with capability diagnostics; Stage 18 does not
  invent remote-store path translation.
- Future external/site build service work can implement the build-service
  protocol without changing named build target definitions.

Compatibility constraints:

- Local, subprocess, standalone SLURM, and Stage 17 Docker behavior must remain
  unchanged when users do not select container build targets or Apptainer
  execution.
- Default imports, CLI help, default preflight for unrelated executors, and
  `make validate-pr` must not require Docker, Apptainer, Singularity, SLURM,
  images, registries, network access, fakeroot support, or a cluster.
- Existing runtime profile merge behavior should be extended through adapter
  namespaces, not semantic stage spec fields.
- Persisted metadata must not contain raw adapter payloads, raw environment
  values, registry credentials, or unbounded command output.
- Build outputs and image identities are provenance/evidence by default, not
  semantic cache keys for stage reuse unless a later roadmap stage explicitly
  defines image-as-input policy.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Package and ownership shape for shared build records, Apptainer behavior, Docker build adapters, and SLURM composition. | FR-1, FR-2, FR-3, FR-6 | 1 | recorded recommendation | Keep shared container/build records under executor ownership; put Apptainer-specific command/build/executor behavior under `loom.pipeline.executors.apptainer`; extend Docker only for Docker-specific build adapters; extend SLURM only at the command-wrapping composition point. | Prevents build/runtime logic from leaking into runner, stores, diagnostics, CLI, or semantic pipeline specs. | Repo boundaries and Stage 17 plan give a clear recommendation. | resolved; design-safety reviewed |
| DAQ-2 | Public runtime/profile config namespaces for execution and build targets. | DAQ-1, FR-6, FR-7, FR-8 | 2 | recorded recommendation | Preserve narrow `container` execution options; add a separate shared `container_build` namespace for named build targets and build-service options; keep `docker`, `apptainer`, and `slurm` runtime-specific namespaces. | This is durable public config surface and directly affects Stage 17 compatibility and Stage 18 examples. | Stage 17 already locked the `container` namespace; separating build config avoids widening it into a universal orchestration API. | resolved; design-safety reviewed |
| DAQ-3 | Apptainer/Singularity executor naming and alias policy. | FR-1 | 3 | recorded recommendation | Treat `apptainer` as the primary executor/runtime name and `singularity` as a compatibility executor name that reuses Apptainer adapter semantics while recording the actual selected command. | Public executor names and persisted runtime metadata are durable. | Feature docs recommend both names and no source evidence requires divergent semantics. | resolved; design-safety reviewed |
| DAQ-4 | Direct Apptainer executor lifecycle. | DAQ-1, DAQ-3, FR-1 | 4 | recorded recommendation | `ApptainerExecutor` should mirror the subprocess/Docker prepared-worker path: build the worker command, wrap it in `apptainer exec`, run through a fakeable command runner, read the worker result, and return normal stage results/failures. | Avoids a second runner and preserves parent-owned lifecycle/finalization. | Existing `SubprocessExecutor` and Stage 17 Docker planning provide the clear pattern. | resolved; design-safety reviewed |
| DAQ-5 | SLURM-container composition surface. | DAQ-1, DAQ-3, DAQ-4, FR-2 | 5 | recorded recommendation | Reuse existing `slurm-single-job` and `slurm-afterok` descriptors and v7 live submission paths; wrap generated Loom command argv in Apptainer at planning/rendering time; do not add `slurm-apptainer` executor names in Stage 18. | This affects public executor selection, manifests, scripts, live submission, and continuation semantics. | User explicitly requested existing machinery; source shows SLURM already owns deterministic argv/script/manifests. | resolved; design-safety reviewed |
| DAQ-6 | Run/artifact path semantics inside Apptainer and SLURM scripts. | DAQ-4, DAQ-5, FR-1, FR-2 | 6 | recorded recommendation | Continue fail-closed path parity for run directories and local artifact roots; do not add host/container path translation in Stage 18. | Incorrect path handling risks failed workers, lost outputs, or misleading provenance. | Stage 17 design accepted path parity and current worker/store paths are host paths. | resolved; design-safety reviewed |
| DAQ-7 | Shared dynamic build model for Docker and Apptainer. | DAQ-1, DAQ-2, FR-6, FR-7 | 7 | recorded recommendation | Add shared named build targets with `if_stale` default, `always`, and `never`; targets produce Docker image refs or Apptainer SIF refs through runtime-specific builders; stages inherit/select targets. | This is the core user-visible build-once/reuse-across-stages behavior. | User confirmed Stage 18 should own this generic phase; the remaining exact field names can be implementation-plan details. | resolved; design-safety reviewed |
| DAQ-8 | Local build-service contract shape. | DAQ-7, FR-4, FR-8 | 8 | recorded recommendation | Model build service as a foreground local request/result protocol with fakeable implementation; no daemonized queues, external build services, site adapters, registry auth, or image publishing. | Service scope affects authority, output locations, logs, credentials, and failure semantics. | User confirmed local-only and foreground/local. | resolved; design-safety reviewed |
| DAQ-9 | Apptainer SIF build source and command boundary. | DAQ-7, DAQ-8, FR-3 | 9 | recorded recommendation | Support explicit `apptainer build` from user-authored definition files and explicit local/URI sources accepted by Apptainer; record fakeroot/temp/cache/output choices when configured; do not add implicit conversion/auth helpers. | SIF builds may require network, credentials, temporary storage, fakeroot, or site policy; Loom must keep those explicit. | User confirmed the source boundary after Apptainer docs were consulted. | resolved; design-safety reviewed |
| DAQ-10 | Scheduler/container resource, GPU, and rank boundary. | DAQ-5, FR-5 | 10 | recorded recommendation | SLURM owns CPU, memory, node/task, and wall-time allocation in SLURM modes; Apptainer may expose explicit runtime flags such as `--nv`/`--rocm`; Loom does not choose MPI ranks, launcher policy, PMI/PMIx compatibility, or multi-node topology. | Prevents Loom from becoming a site-specific MPI or cluster orchestration layer. | User confirmed this direction; Apptainer docs support configured launcher rendering but not generic rank policy. | resolved; design-safety reviewed |
| DAQ-11 | Provenance, redaction, and fingerprint policy. | DAQ-4, DAQ-7, DAQ-8, DAQ-9 | 11 | recorded recommendation | Persist redacted build/runtime/command/environment/image/SIF/scheduler facts as provenance or executor metadata; do not make container image identity a semantic stage fingerprint by default. | Keeps records inspectable without leaking secrets or changing resume semantics. | Stage 17 and runtime-resource docs give the clear precedent. | resolved; design-safety reviewed |
| DAQ-12 | Preflight and validation defaults. | DAQ-3 through DAQ-11 | 12 | auto-approved | Add selected-executor/build-target checks with stable IDs; keep default validation fake/local/offline; gate real Docker, Apptainer, SIF build, and SLURM smoke checks behind explicit opt-in. | Protects default developer workflows while still making HPC/container readiness diagnosable. | Design-safety review upheld this only with explicit no-network/no-runtime defaults and stable check-ID obligations. | resolved; design-safety reviewed |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Future-roadmap impact | Interface, adapter, or protocol impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Package and ownership shape | Shared build records stay in executor-owned container modules; Apptainer behavior lives in `loom.pipeline.executors.apptainer`; Docker receives only Docker-specific build adapter extensions; SLURM receives only command-wrapping composition. | Not surfaced; repo-supported recommendation. | Build records in runtime/config/stores; Apptainer logic in shared container records; new scheduler implementation. | Matches `docs/structure.md` and Stage 17's executor-owned shared-record decision. | Keeps high-level lifecycle modules free of backend command details. | Future build services can implement the shared build protocol without changing runner/store ownership. | Stage 19 can consume facts without backend-specific policy. | Shared records are plain-data value objects; backend command runners remain adapter-local. | Import-boundary, namespace, and adapter ownership tests. | Revisit if Stage 17 lands incompatible shared container package names or if build records need store-owned authority. | resolved |
| DAQ-2 | Public config namespaces | `container` remains execution-time image/workdir/mount/env/target selection; `container_build` owns named build target definitions and local build-service options; runtime-specific details stay in `docker`, `apptainer`, and `slurm`. `container_build` follows existing opaque adapter-namespace replacement semantics unless a future typed merge model is explicitly designed. | User confirmed shared build targets and accepted exact field names as design detail. | Putting build targets into `docker`/`apptainer` only; widening `container` with all build-service details; adding semantic stage-spec fields; silently inventing per-target deep merge inside one adapter namespace. | Separating build config preserves Stage 17's narrow generic namespace while enabling shared build reuse. Existing profile merge rules avoid a hidden new config merge policy. | Makes public config easier to validate and document. | External build services can later attach to `container_build` without changing execution options. | Stage 19/20/21 receive stable build/result metadata. | Executor descriptors claim consumed namespaces; profile merge keeps namespaces opaque plain data. | Runtime/profile config tests and examples for run-level defaults, stage selection, and complete-namespace override behavior. | Revisit if users need per-target overlay merging or Stage 17 source hard-codes a conflicting namespace strategy. | resolved |
| DAQ-3 | Apptainer/Singularity naming | `apptainer` is primary; `singularity` is a compatibility executor name that uses the same adapter records and command builders while metadata records the command actually invoked. | Not surfaced; feature-doc-supported recommendation. | Separate divergent `singularity` semantics; hidden fallback without persisted command identity. | Current Apptainer/Singularity scope is CLI-compatible execution, not divergent runtime behavior. | Avoids duplicate implementations. | Allows sites with only `singularity` command to run while preserving metadata clarity. | Future plugin discovery can expose either command. | Runtime descriptors for both names can share adapter namespace claims. | Descriptor, command detection, and metadata tests for both names. | Revisit if Singularity behavior diverges enough to require separate option semantics. | resolved |
| DAQ-4 | Direct Apptainer lifecycle | Mirror the prepared-worker subprocess/Docker pattern with `ApptainerExecutor.requires_prepared_worker_request = True`. | Not surfaced; repo-supported recommendation. | Direct in-process stage execution inside Apptainer; whole-controller-in-container; executor-owned finalization. | The durable worker path already solves stage reconstruction and result handoff. | Keeps executor code focused on invocation and failure normalization. | Other container runtimes can follow the same lifecycle. | Stage 19 can wrap process/failure facts uniformly. | Reuses `Executor`, `StageExecutionRequest`, `StageExecutionResult`, and worker-result contracts. | Fake-runner executor tests for success, worker failure, launch failure, and process/worker conflict. | Revisit only if path parity or authority handoff makes worker reconstruction impossible. | resolved |
| DAQ-5 | SLURM-container composition | Existing `slurm-single-job` and `slurm-afterok` modes build Loom worker/continuation argv, then wrap that argv in Apptainer for scripts and live submissions. Container builds resolve on the controller/submit side before script rendering or live submission; generated scripts execute resolved images/SIFs rather than running builds. | User requested existing Loom machinery and SLURM resource submission. | New `slurm-apptainer` executor names; parallel scheduler implementation; running the controller inside the container; hiding build commands inside generated batch scripts. | Existing SLURM code already owns deterministic scripts, manifests, live submission, status, and cancellation. User confirmed foreground/local builds. | Minimizes scheduler churn and keeps reviewable diffs. | Future scheduler/container combinations can add composition hooks without new scheduler backends. | Stage 19 reliability sees normal submitted-operation facts and can distinguish build failures from submitted job failures. | Adds an argv wrapper/composition helper and descriptor namespace claims; no new submitted-operation schema by default. | Script-rendering, manifest, fake live submission, build-before-submit ordering, and status/cancel regression tests. | Revisit if a future site build service intentionally builds inside allocations. | resolved |
| DAQ-6 | Path parity | Require path-parity binds for run directories and local artifact roots; fail closed for non-local, non-mountable, or mismatched paths. | Not surfaced; Stage 17 precedent. | Host/container path translation; implicit remote-store staging; best-effort default binds. | Current worker/store metadata uses host-visible file paths and Apptainer binds may be site-restricted. | Simple failure behavior and fewer metadata rewrites. | A future path-mapping protocol can be added when a concrete remote/HPC need requires it. | Stage 21 cleanup can consume host-visible paths without translation state. | Shared mount/path validation helpers stay runtime-neutral. | Preflight and executor tests for missing binds, unwritable roots, and mismatched target paths. | Revisit for remote stores, non-local authority, or HPC sites where path parity is impossible. | resolved |
| DAQ-7 | Shared build model | Named build targets use `if_stale` by default with `always` and `never`; targets produce Docker image refs or Apptainer SIF refs through runtime-specific builders and can be selected by many stages. Build evidence is run-local by default, while actual outputs use explicit adapter output refs rather than implicit global caches or committed stage outputs. | User explicitly confirmed shared/generic build phase, dynamic build/run, no per-stage recipe files, and policies. | Per-stage recipe files; manual prebuild-only flow; runtime-specific duplicate build config; rebuild before every stage; silently inventing a cross-run cache or treating build outputs as stage outputs. | This matches the core user-visible behavior and keeps build evidence inspectable. | Centralizes build policy and reduces duplicated runtime-specific code. | Future build adapters can use the same target/result records. | Stage 19 can reason about build failure/retry separately from stage execution. Stage 21 can clean derived evidence without confusing it with stage output authority. | Shared build request/result protocol; runtime-specific builder adapters; explicit output refs for Docker images and Apptainer SIFs. | Unit/contract tests for policy, stale keys, reuse, invalid targets, output refs, and run-local evidence versus output location. | Revisit if build keys need stronger network/registry content identity or a global build cache is selected. | resolved |
| DAQ-8 | Local build service | Foreground local build request/result service with fakeable runner; records local worker identity, command projection, logs, output ref, and diagnostics. | User confirmed local-only and foreground/local. | Daemon build pool; Apptainer remote build; configured site service; registry publishing/auth helper. | Keeps Stage 18 testable and avoids external service policy. | Service boundary is narrow enough to maintain and fake. | Future external/site builders can implement the request/result protocol. | Stage 20 can emit build events; Stage 21 can clean derived outputs. | Local implementation plus protocol; no persistent daemon lifecycle. | Fake service tests, command-result tests, failure mapping, and opt-in real local smoke. | Revisit when external/site build services are explicitly planned. | resolved |
| DAQ-9 | Apptainer SIF build boundary | Support explicit `apptainer build` from definition files and explicit local/URI sources; record configured fakeroot/temp/cache/output flags; validate output SIF. | User confirmed after Apptainer docs review. | Implicit image conversion; registry/auth helper; site-specific build policy; generating domain-specific definition files. | Apptainer docs show build flexibility and environment constraints; Loom should expose explicit plumbing, not infer policy. | Keeps SIF support bounded and diagnosable. | Later conversion/auth helpers can be added without changing direct SIF build records. | Stage 19 can classify build failures separately. | Apptainer build options and builder adapt shared build request into argv. | Fake `apptainer build` tests, preflight for command/fakeroot/temp/output, and docs snippets. | Revisit if users need authenticated registries or site build services. | resolved |
| DAQ-10 | Resources, GPU, and rank boundary | SLURM enforces CPU/memory/node/task/wall-time in scheduler modes; Apptainer flags expose container access such as GPU `--nv`/`--rocm`; MPI/rank orchestration remains user/site-owned. | User confirmed Loom should not own rank-level orchestration unless necessary. | Loom-selected MPI ranks; automatic `mpirun`/`srun` policy; double-enforcement promises; site module policy. | Keeps Loom domain-neutral and aligns with SLURM/Apptainer docs. | Avoids hardcoding site-specific cluster behavior. | Future MPI support can be designed separately if needed. | Reliability policy can distinguish scheduler allocation from container runtime flags. | Resource descriptors and preflight must state ownership precisely. | Resource mapping, GPU flag, scheduler/container compatibility, and docs examples. | Revisit only if a concrete Stage 18 blocker proves configured commands are insufficient. | resolved |
| DAQ-11 | Provenance/redaction/fingerprints | Persist redacted build/runtime/command/environment/image/SIF/scheduler facts as executor/provenance metadata; do not include image identity in semantic fingerprints by default. Apptainer execution uses explicit/clean environment handoff by default, with broader inheritance only through explicit config. | Not surfaced; Stage 17 and runtime-resource precedent. | Persisting raw env/build args; treating image digest as mandatory cache key; omitting build provenance; relying on Apptainer's default host environment passthrough. | Adds reproducibility evidence without leaking secrets or changing resume semantics. Clean environment defaults align Apptainer behavior with the confirmed redaction boundary. | Keeps metadata shareable and stable. | Future image-lock or semantic-input policy can opt in explicitly. | Stage 20/21 can consume redacted facts. | Shared redaction helpers, safe metadata projections, and explicit env projection helpers. | Tests for no raw adapter/env payloads, bounded output, redacted argv, provenance summaries, and clean-env command construction. | Revisit for image lock files, image-as-semantic-input policy, or a future secret-management feature. | resolved |
| DAQ-12 | Preflight and validation defaults | Stable selected-executor/build-target checks; fake/local/offline tests by default; real Docker/Apptainer/SIF/SLURM smoke tests opt-in only. | User confirmed default fake/local validation. | Required real runtime/cluster tests; default network/registry/fakeroot probes; no preflight. | Existing preflight and SLURM fake-command tests provide the pattern. | Keeps CI deterministic and actionable. | Optional probes can grow later. | Stage 19 can trust stable diagnostic IDs. | Diagnostics consume safe summaries and selected namespaces. | Stable check-ID tests, fake builder/runner integration, and optional marked smoke tests. | Revisit if release policy requires live runtime evidence. | resolved |

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | recorded recommendation | Considered whether build records should move to runtime or stores; rejected because executor ownership preserves current source-tree boundaries and keeps build facts derived evidence. | FR-1, FR-2, FR-3, FR-6 | record recommendation | design-safety reviewed |
| DAQ-2 | recorded recommendation | Considered widening `container`; rejected because Stage 17 design-safety limited it to execution-time records. A separate `container_build` namespace is safer public surface as long as Stage 18 records the current whole-namespace replacement merge semantics instead of implying per-target deep merge. | FR-6, FR-7, FR-8 | record recommendation with merge-semantics guardrail | design-safety reviewed |
| DAQ-3 | recorded recommendation | Considered separate Singularity semantics; rejected until concrete divergence appears. | FR-1 | record recommendation | design-safety reviewed |
| DAQ-4 | recorded recommendation | Considered direct stage execution or whole-controller container mode; rejected because prepared-worker lifecycle already exists and user selected existing machinery. | FR-1 | record recommendation | design-safety reviewed |
| DAQ-5 | recorded recommendation | Considered `slurm-apptainer` executor names and hidden build steps in batch scripts; rejected for Stage 18 because existing SLURM modes/manifests can compose by wrapping resolved execution argv after submit-side build resolution. | FR-2 | record recommendation with submit-side build-ordering guardrail | design-safety reviewed |
| DAQ-6 | recorded recommendation | Considered path translation; rejected for Stage 18 because current run-store/artifact paths are host paths and Stage 17 accepted fail-closed parity. | FR-1, FR-2 | record recommendation | design-safety reviewed |
| DAQ-7 | recorded recommendation | Considered runtime-specific build models, implicit global image caches, and treating build outputs as stage outputs; rejected because user selected a shared/generic build layer with named targets, explicit output refs, and run-local build evidence. | FR-6, FR-7 | record recommendation with output-ref/evidence guardrail | design-safety reviewed |
| DAQ-8 | recorded recommendation | Considered daemon/external build-service shapes; rejected by user-confirmed local-only foreground boundary. | FR-4, FR-8 | record recommendation | design-safety reviewed |
| DAQ-9 | recorded recommendation | Considered broad conversion/auth helpers; rejected because user confirmed explicit Apptainer build sources and roadmap defers auth/site policy. | FR-3 | record recommendation | design-safety reviewed |
| DAQ-10 | recorded recommendation | Considered automatic MPI/rank orchestration; rejected by user confirmation and site-specific risk. | FR-5 | record recommendation | design-safety reviewed |
| DAQ-11 | recorded recommendation | Considered image identity as a stage fingerprint and Apptainer's broad default host-environment inheritance; rejected to preserve current resume semantics, redaction, and reproducible explicit environment handoff. | FR-3, FR-6, FR-7 | record recommendation with clean-env guardrail | design-safety reviewed |
| DAQ-12 | auto-approved | Existing preflight/fake-command patterns fit. Design safety upheld auto-approval after requiring stable check IDs and no default runtime/network/fakeroot probes. | all | uphold auto-approval with cheap-check guardrails | design-safety reviewed |

## Design Safety Review

| Finding | Affected decision or requirement | Future-roadmap or compatibility risk | Interface, adapter, or protocol reuse risk | Recommended planning revision | Status |
| --- | --- | --- | --- | --- | --- |
| `container_build` is safe as a separate namespace only if Stage 18 accepts current opaque adapter-namespace replacement semantics. | DAQ-2, DAQ-7, FR-6, FR-7 | Users or later phases could otherwise assume per-target deep merge and force a public config compatibility break. | A shared build-target protocol remains reusable, but namespace-local typed merge is a separate future design. | Record complete-namespace override semantics in data flow, design decisions, examples, and validation. | recommendation recorded |
| Build evidence and build outputs need distinct placement rules. | DAQ-7, DAQ-8, DAQ-11, FR-6, FR-8 | Stage 19/21 could confuse local build evidence, reusable image refs, and committed stage outputs, leading to wrong retry/cleanup behavior. | Output refs stay adapter-specific: Docker image ref/tag/digest-like identity or configured Apptainer SIF path; build evidence stays run-local. | Record no implicit global cross-run cache and no committed stage output by default. | recommendation recorded |
| SLURM plus Apptainer must resolve builds before script rendering or live submission. | DAQ-5, DAQ-7, DAQ-8, FR-2, FR-4 | Hidden builds inside batch scripts would blur local build failures with scheduler/job failures and make dry-run scripts less reviewable. | SLURM wrapping remains an argv/script composition hook, not a new scheduler or build executor. | Record submit-side foreground/local build ordering and require generated scripts to run only resolved images/SIFs. | recommendation recorded |
| Apptainer environment defaults need to be explicit and clean. | DAQ-4, DAQ-11, FR-1 | Default host-environment passthrough can leak secrets and make runs non-reproducible. | Environment projection helpers can be shared with container metadata redaction without creating a secret-management feature. | Default to clean-environment behavior plus explicit env projection; broader inheritance requires explicit config. | recommendation recorded |
| Path parity, resource ownership, and rank boundaries are still the right Stage 18 cut. | DAQ-6, DAQ-10, FR-2, FR-5 | Future remote stores, path translation, or MPI support may need a dedicated protocol, but adding it now would expand the stage materially. | Fail-closed path validation and scheduler-owned resource allocation are reusable constraints for Stage 19 reliability facts. | Keep fail-closed path parity and no Loom-owned MPI/rank orchestration; retain revisit triggers. | upheld |
| DAQ-12 can be auto-approved only with stable IDs and cheap defaults. | DAQ-12 | Stage 19 diagnostics depend on stable check IDs; default network/runtime/fakeroot probes would make CI and local preflight brittle. | Preflight consumes safe selected namespaces and fake builders/runners by default. | Reclassify DAQ-12 from auto-approved candidate to auto-approved with no-network/no-runtime defaults. | upheld and reclassified |
| Stage 17 source absence is an accepted residual risk, not a design-safety blocker. | DAQ-1, DAQ-2, DAQ-6, DAQ-11 | If Stage 17 lands incompatible shared container contracts, Stage 18 implementation planning or Phase 1 execution planning may need adjustment. | The Stage 18 design remains compatible with expected Stage 17 contracts; the implementation-plan draft refreshed current source and Phase 1 must refresh again before code starts. | Record the source-refresh result in the implementation plan; rerun design-safety only if Stage 17 changes shared contracts materially. | accepted risk |

Gate result:

- Status: passed
- Reviewer: local roadmap-stage design-safety review on 2026-05-17.
- Blockers:
  - None.
- Auto-approved decisions upheld:
  - DAQ-12 is upheld as auto-approved after adding stable check-ID,
    fake/local/offline, and no default runtime/network/fakeroot-probe
    obligations.
- Auto-approved or candidate decisions overturned:
  - None. DAQ-12 moved from auto-approved candidate to auto-approved after
    guardrails were recorded.
- Recorded recommendations:
  - DAQ-1 through DAQ-11 remain recorded recommendations.
  - Keep `container_build` as a shared namespace but document whole-namespace
    replacement under current runtime-profile adapter semantics.
  - Keep actual build outputs as explicit adapter output refs and build
    evidence as run-local evidence.
  - Resolve local foreground builds before SLURM script rendering and before
    live `sbatch`.
  - Default Apptainer execution to clean environment handoff plus explicit env
    projection.
  - Avoid a universal command-runner abstraction in Stage 18; reuse shared
    build request/result records and keep runtime command runners
    adapter-local.
- Future-roadmap impact summary:
  - Stage 19 can classify build failures separately from submitted job and
    runtime failures.
  - Stage 20 can emit redacted build/run facts without importing backend
    command semantics.
  - Stage 21 can clean run-local evidence without confusing it with stage
    output authority or global image cache state.
- Generic interface, adapter, and protocol assessment:
  - The shared build request/result/output-ref contract is generic enough for
    Docker and Apptainer while preserving runtime-specific command builders.
  - `container_build` is acceptable as a separate shared namespace under
    current opaque namespace replacement semantics.
  - SLURM plus Apptainer remains scheduler command composition; Loom does not
    add rank-level orchestration or a new scheduler implementation.
- Planning revisions required:
  - Completed in this pass for design decisions, data flow, practical design
    notes, validation obligations, readiness, and handoff notes.
  - Examples, validation strategy, and phase shaping are now recorded.
- Accepted risks:
  - Stage 17 source is not present in this checkout; refresh actual Stage 17
    source and implementation-plan assumptions before implementation-plan
    drafting.
  - Path translation, external/site build services, registry/auth helpers,
    image lock semantics, and MPI/rank orchestration remain deferred.
- Revisit triggers:
  - Stage 17 lands incompatible shared container contracts.
  - Users need per-target overlay/deletion semantics for `container_build`.
  - A site build service intentionally builds inside scheduler allocations.
  - Image identity becomes a semantic stage input or lock-file policy.
  - Remote stores or HPC sites make path parity insufficient.

## Practical Design Notes

Public Python API surface:

- Import-light shared container/build records under executor ownership.
- Lazy exports for `ApptainerExecutor` and any runtime-specific command result
  records, following the existing executor package pattern.
- No top-level `loom.__init__` exports and no optional Docker/Apptainer/SLURM
  imports on default package import.

CLI surface:

- Existing `loom run --executor apptainer` and
  `loom run --executor singularity` selection paths.
- Existing `loom run --executor slurm-single-job` and
  `loom run --executor slurm-afterok` paths with Apptainer wrapping selected
  through runtime/profile adapter options.
- Existing preflight CLI surfaces gain selected-executor/container-build checks.
- No separate Docker/Apptainer build CLI group in Stage 18.

Persisted records and file layout:

- Build request/result evidence, resolved image/SIF output refs, redacted
  command projections, bounded command output, and cheap identity facts are
  persisted under run-local generated/evidence artifacts or executor metadata.
- Actual build outputs are not implicitly copied into run-local evidence:
  Docker outputs remain explicit image refs or digest-like identities, and
  Apptainer outputs remain configured SIF paths unless a later artifact policy
  says otherwise.
- SLURM scripts/manifests remain in existing generated SLURM artifact paths,
  with Apptainer-wrapped commands visible in the script and safe summaries in
  manifests.
- Build outputs are derived artifacts/evidence, not authority state or
  committed stage outputs by default.

Import boundaries and dependencies:

- No Python Docker SDK, Apptainer SDK, SLURM SDK, registry SDK, or mandatory
  runtime dependency.
- Shared build records do not import runtime command execution modules.
- Diagnostics import safe validators/summaries only.

Failure modes and diagnostics:

- Missing build target, missing runtime command, invalid build source, stale
  output under `never`, build failure, missing SIF output, invalid binds,
  unwritable roots, unsupported resource mapping, launch failure, worker-result
  failure, and scheduler/container incompatibility all produce structured
  diagnostics or execution/build result records.
- Partial target overrides under current `container_build` namespace
  replacement semantics should be either documented as unsupported or rejected
  with clear validation, rather than silently merging target fragments.
- Default diagnostics are cheap and selected-executor scoped.

Extension points and flexibility boundaries:

- Future external/site build services implement the local request/result
  protocol but are not configured in Stage 18.
- Future path translation, registry auth, image publishing, image lock files,
  MPI/rank orchestration, and site module policy are explicit later work.

Generic interfaces, adapters, and protocols:

- `container_build` is the shared build-target contract.
- Under existing runtime-profile adapter semantics, `container_build` is
  replaced as a whole namespace at higher precedence; Stage 18 does not add
  per-target deep merge.
- Runtime-specific builders adapt shared requests to Docker or Apptainer argv.
- Command runners remain runtime-specific; build request/result records are the
  shared protocol.

Future-roadmap compatibility:

- Stage 19 reliability can wrap build, process, and submitted-operation facts
  without backend-specific retry semantics.
- Stage 20 event sinks can project redacted build/run facts.
- Stage 21 cleanup can consume generated-output/log facts without treating
  them as authority truth.

Maintainability assessment:

- The design is maintainable if Stage 18 lands shared build records first,
  runtime-specific builders second, direct Apptainer execution third, SLURM
  composition fourth, and preflight/docs after the behavior is stable.
- The main risks are public config creep, `container_build` becoming a registry
  or service framework, and SLURM composition drifting into rank orchestration.
- SLURM scripts should stay execution-only artifacts for resolved images/SIFs;
  build commands remain in the submit-side foreground/local build path.

Extensibility assessment:

- The design preserves Docker/Apptainer reuse through shared build
  request/result records and preserves scheduler independence by keeping
  wrapping at the argv/script composition point.
- It intentionally defers a universal command-runner abstraction until multiple
  runtime adapters prove enough shared behavior.

Flexibility and expansion assessment:

- The design supports local foreground builds now and future service adapters
  later without changing named target selection.
- It is less flexible for path translation and MPI launch policy by design;
  those remain explicit revisit triggers instead of implicit heuristics.

Scalability and future compatibility:

- `if_stale` target reuse avoids rebuilding per stage.
- Stage 18 does not add background queues or distributed build coordination;
  scaling beyond foreground local builds is future external/site build-service
  work.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Stage 18 planning and implementation-plan drafting started before Stage 17 source is present in this checkout. | The user requested Stage 18 planning from the roadmap, and adjacent Stage 17 planning artifacts provide expected prerequisite context. | Refresh source and Stage 17 implementation-plan assumptions before Phase 1 execution planning; rerun design-safety only if Stage 17 changes shared contracts materially. |
| SIF build support expands the roadmap's original runtime-oriented boundary. | User clarified that Stage 18 needs `.sif` build/construction handling. | Revisit if build support starts requiring registry auth helpers, site-specific build services, or broad image-conversion policy. |
| Build-service support expands runtime/build scope. | User clarified that Stage 18 needs build-service support for the container, local-only for now. | Revisit if the service contract starts owning registry/auth, image distribution, external/site build adapters, daemon lifecycle beyond the stage, or site-specific policy. |
| Shared dynamic build layer affects Stage 17 Docker planning. | User clarified Docker and Apptainer both need dynamic build-and-run support, then selected Stage 18 as the owner for the shared/generic container-build phase. | Revisit if Stage 17 Docker implementation lands first with assumptions that block Stage 18 from adding shared Docker build semantics. |
| `container_build` uses whole-namespace replacement semantics. | This matches existing runtime-profile adapter behavior and avoids inventing a hidden merge policy during Stage 18. | Revisit if users need per-target overlay, deletion, or typed merge semantics. |
| No implicit global build cache. | Stage 18 is local foreground build/reuse with explicit output refs, not a cache or registry authority layer. | Revisit when external/site build services, image locks, or cross-run cache policy are intentionally designed. |

## Examples And Demonstrations

| Example | Behavior demonstrated | Loom context | Required docs/tests | Status |
| --- | --- | --- | --- | --- |
| Direct Apptainer stage execution | A prepared stage attempt runs inside an Apptainer/Singularity image and returns through normal worker result handling. | Standalone executor parity with Docker/subprocess. | Fake-runner executor test, command-builder test, and docs snippet. | confirmed |
| Apptainer SIF build | A user-authored definition file or explicit source is built into a `.sif` with recorded command, output path, and build evidence. | Image construction provenance before execution/submission. | Fake build-runner test, preflight checks, and docs snippet. | confirmed |
| Local container build service | A foreground local builder accepts an explicit build request and returns a recorded image/SIF output reference. | Local build-service path for users who should not build ad hoc on every run path. | Fake service contract test, output-ref test, and optional real local smoke. | confirmed |
| Shared build-and-run target | One run/profile build target is built once or reused and then selected by several stages. | Avoid per-stage container recipe files while preserving stage-level executor selection. | Config/profile example, fake build/run integration test, and provenance readback. | confirmed |
| Complete `container_build` namespace override | A higher-precedence profile replaces the whole shared build-target namespace rather than merging individual target fragments. | Documents current adapter namespace semantics and prevents surprising partial overrides. | Runtime-profile merge test and docs example showing full override. | confirmed |
| Build output/evidence separation | Build request/result evidence stays run-local, while Docker image refs and Apptainer SIF paths remain explicit output refs. | Protects Stage 19 reliability and Stage 21 cleanup from confusing evidence with stage output authority. | Record serialization test, reuse test, and docs explanation. | confirmed |
| SLURM plus Apptainer dry-run | Generated SBATCH script runs the Loom stage/continuation command inside `apptainer exec` and remains inspectable. | HPC review and reproducibility workflow. | Script-rendering contract test and example output. | confirmed |
| Live SLURM plus Apptainer | Existing live SLURM submission records and status/cancel paths are reused for containerized jobs. | Optional cluster workflow. | Fake `sbatch`/status integration test; real SLURM/Apptainer optional. | confirmed |
| Submit-side build before SLURM rendering/submission | Local foreground builds complete before dry-run script rendering or live `sbatch`; generated scripts contain no build commands. | Keeps build failures separate from scheduler/job failures. | Build-before-render ordering test and script text assertion. | confirmed |
| Clean Apptainer environment | `apptainer exec`/`singularity exec` uses clean environment behavior plus explicit env projection unless config opts into broader inheritance. | Redaction and reproducibility boundary for HPC sites. | Command-builder tests and metadata redaction tests. | confirmed |
| Apptainer/container-build preflight | Missing command, missing image/build output, invalid binds, unwritable run dir, missing env, unsupported resources, or build-environment gaps are reported. | Cheap readiness diagnostics. | Stable check ID tests and JSON output examples. | confirmed |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Package/import boundaries | Default imports and CLI help do not require Apptainer, Singularity, Docker, SLURM, images, or network. | Package/import tests and CLI smoke for unrelated executors. | package / unit | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| Runtime-profile config semantics | `container`, `container_build`, `docker`, `apptainer`, and `slurm` namespaces are consumed by the right descriptors, and `container_build` higher-precedence values replace the whole namespace. | Runtime-profile merge tests, descriptor namespace tests, and config examples. | unit / contract | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| Shared build contracts | Build target/source/policy/request/result/output-ref records serialize cleanly, redact secrets, and stay import-light. | Unit and contract tests for validation, serialization, redaction, and output-ref shape. | unit / contract | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| Build policy and reuse | `if_stale`, `always`, and `never` produce deterministic build/reuse/fail decisions without fetching network-backed URI contents just to compute default keys. | Unit tests for keying, stale checks, invalid targets, and diagnostic cases. | unit | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| SIF build command and records | Build inputs, output path, fake command execution, temp/cache/fakeroot summaries, output validation, and failures are deterministic and redaction-safe. | Unit and contract tests for build source validation and command projection. | unit / contract | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| Docker build adapter compatibility | Stage 18 shared build layer can drive Docker-specific fake build semantics without moving Docker execution behavior into shared records. | Fake Docker builder tests and shared build adapter contract tests. | unit / integration | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| Local build-service contract | Build requests/results, local worker identity, output references, logs, and failures are recorded without assuming Apptainer remote-build or external site service support. | Unit, contract, and integration tests with fake local build service. | contract / integration | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| Command construction | `apptainer exec`/`singularity exec` argv is deterministic, redaction-safe, clean-env by default, and shell-free where it is run directly. | Unit tests for image, binds, workdir, env projection, resources, GPU flags, and inner worker command. | unit | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| Direct executor result handling | Process failures, worker-result failures, missing/invalid results, and process/worker conflicts map to normal stage failures. | Fake-runner executor tests. | unit / integration | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| SLURM script composition | Generated scripts compose SBATCH directives and Apptainer-wrapped worker command without breaking manifests, and contain no hidden Docker or Apptainer build commands. | Contract/integration tests with fake store, deterministic scripts, and build-before-render/submission ordering. | contract / integration | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| Live SLURM reuse | Live SLURM plus Apptainer uses existing `sbatch`, status, cancel, submitted-operation, and fake command-runner paths. | Fake live-submission integration tests and existing SLURM regression tests. | integration | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| Preflight | Selected-executor diagnostics are stable, cheap, actionable, and do not run default network/runtime/fakeroot probes. | Stable check IDs, pass/fail cases, selected namespace cases, and JSON output. | contract / integration | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| Documentation examples | Feature docs show named build targets, SIF build, direct Apptainer execution, SLURM composition, clean-env defaults, output refs, and deferrals. | Docs examples and generated script snippets that align with tests. | docs | Exact files assigned by implementation plan; final gate `make validate-pr`. | confirmed |
| Opt-in real runtime/cluster | Real Docker, Apptainer/Singularity, SIF build, and SLURM behavior can be smoke-tested when explicitly enabled. | Marked or manual tests only; default CI does not require runtimes, cluster, images, registries, fakeroot, or network. | opt-in | Optional command names assigned by implementation plan; not required for default `make validate-pr`. | confirmed |

## Phase Sketch

### Phase 1 - Shared Build Contracts And Config Semantics

Goal:

- Establish the shared Docker/Apptainer build contract before adding runtime
  command behavior.

Scope:

- Add import-light shared build target/source/policy/request/result/output-ref
  records under executor-owned container modules.
- Add validation, serialization, redaction, output-ref, and build-key helpers.
- Wire runtime-profile/descriptor consumption for `container_build` using
  existing whole-namespace replacement semantics.
- Preserve Stage 17 `container` execution semantics and runtime-specific
  `docker`, `apptainer`, and `slurm` namespaces.

Out of scope:

- Running Docker or Apptainer commands.
- Local build-service execution.
- Direct Apptainer stage execution or SLURM script composition.

Acceptance criteria:

- Public records are plain data, import-light, redaction-safe, and
  schema-versioned where needed.
- `container_build` complete-namespace override behavior is validated and
  documented.
- No default import or unrelated CLI path requires Docker, Apptainer,
  Singularity, SLURM, images, or network.

Test expectations:

- Package: import-boundary and CLI help checks.
- Unit: record validation, serialization, redaction, output refs, and build
  keying.
- Contract: runtime-profile namespace replacement and descriptor namespace
  claims.
- Integration: none unless existing profile tests require it.
- E2E: none.
- Opt-in: none.

Design impact:

- Locks the reusable public build contract and config merge semantics.

Future compatibility:

- Gives Stage 19-21 stable build facts without backend command imports.

Alternatives rejected:

- Per-runtime-only build config, per-target deep merge, and widening
  `container` into a universal build namespace.

Debt introduced:

- Whole-namespace `container_build` replacement is accepted until a typed merge
  model is explicitly designed.

Reviewability:

- Small public-contract phase with no live runtime behavior.

### Phase 2 - Local Build Service And Runtime Builders

Goal:

- Implement foreground/local build/reuse behavior for Docker image refs and
  Apptainer SIF refs through the shared build contract.

Scope:

- Add the local build-service/request-result protocol and fake implementation.
- Add runtime-specific builder adapters for Docker build semantics and
  Apptainer `build` argv construction.
- Implement `if_stale`, `always`, and `never` policy decisions, output
  validation, build/reuse/failure records, and run-local build evidence.
- Keep actual build outputs as explicit adapter output refs.

Out of scope:

- External/site build services, daemon queues, registry login/auth helpers,
  publishing, implicit image conversion, or global cross-run image cache.
- Direct Apptainer stage execution.
- SLURM composition.

Acceptance criteria:

- Fake builders can build, reuse, fail, and validate outputs deterministically.
- Apptainer SIF build inputs include user-authored definition files and
  explicit local/URI sources accepted by `apptainer build`.
- Docker and Apptainer builders share request/result records but keep command
  runners adapter-local.

Test expectations:

- Package: optional runtime imports remain absent from default imports.
- Unit: policy decisions, build keying, output refs, command construction,
  redaction, and output validation.
- Contract: local build-service request/result behavior.
- Integration: fake Docker and fake Apptainer builder flows.
- E2E: none.
- Opt-in: optional real local Docker/Apptainer build smoke only.

Design impact:

- Establishes the dynamic build-and-run layer the user requested.

Future compatibility:

- Future external/site builders can implement the same request/result protocol.

Alternatives rejected:

- Per-stage recipe files, manual prebuild-only flow, daemonized build pools,
  and Apptainer remote-build assumptions.

Debt introduced:

- No global cache or image lock policy; image identity remains provenance by
  default.

Reviewability:

- Focused build-layer phase that can be reviewed without scheduler behavior.

### Phase 3 - Direct Apptainer And Singularity Execution

Goal:

- Run prepared stage attempts through Apptainer/Singularity using the normal
  worker/result contract.

Scope:

- Add Apptainer/Singularity descriptors, command availability/version probes,
  command builder, command runner protocol, and direct executor behavior.
- Implement binds, workdir, path-parity validation, selected environment
  projection, clean-env default, GPU flags, image/SIF reference handling, and
  redacted provenance.
- Normalize launch failures, process failures, worker-result failures, missing
  results, and conflicts into normal stage execution results.

Out of scope:

- SLURM script composition and live submission.
- Rank/MPI orchestration, path translation, site modules, or security-sandbox
  claims.

Acceptance criteria:

- `apptainer` is primary and `singularity` is a compatible command/executor
  name with selected command identity recorded.
- Direct execution mirrors the prepared-worker subprocess/Docker pattern.
- Environment handoff is clean/explicit by default.

Test expectations:

- Package: executor imports stay lazy.
- Unit: command construction, path/env/resource option validation, redaction.
- Contract: runtime descriptors and metadata shape.
- Integration: fake-runner executor success/failure flows.
- E2E: default fake execution only.
- Opt-in: optional real Apptainer/Singularity smoke.

Design impact:

- Adds the direct HPC container executor path.

Future compatibility:

- Stage 19 can consume process/runtime facts uniformly across subprocess,
  Docker, and Apptainer.

Alternatives rejected:

- Whole-controller-in-container mode, in-process stage execution inside the
  container, and divergent Singularity semantics.

Debt introduced:

- Path parity is fail-closed; path translation remains a future protocol.

Reviewability:

- Runtime phase is isolated from build-contract and SLURM scheduling changes.

### Phase 4 - SLURM Plus Apptainer Composition

Goal:

- Compose existing SLURM dry-run/live submission machinery with resolved
  Apptainer execution.

Scope:

- Add an argv/script composition point that wraps existing SLURM worker or
  continuation commands in `apptainer exec`.
- Ensure container build resolution completes on the controller/submit side
  before dry-run script rendering or live `sbatch`.
- Preserve generated scripts, submitted-operation manifests, status, cancel,
  resource mapping, failure records, and fake command-runner behavior.
- Record scheduler/container resource ownership and GPU/runtime flags without
  double-enforcement claims.

Out of scope:

- New `slurm-apptainer` executor names, new scheduler implementation, hidden
  build commands in batch scripts, site modules, MPI rank policy, or
  multi-node topology decisions.

Acceptance criteria:

- Dry-run scripts are inspectable and contain Apptainer-wrapped worker commands
  against resolved images/SIFs.
- Live fake submission reuses existing v7 SLURM paths.
- Build failures are recorded before submission and not disguised as job
  failures.

Test expectations:

- Package: no new mandatory SLURM/Apptainer imports.
- Unit: argv wrapping and resource ownership summaries.
- Contract: deterministic script rendering and manifest summaries.
- Integration: fake `sbatch`, status, cancel, and build-before-submit flows.
- E2E: default fake scheduler/container flow.
- Opt-in: optional real SLURM plus Apptainer smoke.

Design impact:

- Delivers the primary HPC execution path while preserving existing scheduler
  authority.

Future compatibility:

- Stage 19 reliability can distinguish build, launch, submitted-operation, and
  worker failures.

Alternatives rejected:

- Parallel scheduler backend, controller-in-container mode, and Loom-owned
  rank orchestration.

Debt introduced:

- Site-specific build-inside-allocation and module policies remain deferred.

Reviewability:

- Scheduler/container behavior lands after direct execution and build output
  contracts exist.

### Phase 5 - Preflight, Docs, And Opt-In Runtime Smoke

Goal:

- Finish selected-executor diagnostics, user-facing docs, examples, and final
  validation evidence.

Scope:

- Add stable preflight check IDs for build targets, runtime command
  availability, build readiness, image/SIF/output presence, bind roots,
  writable paths, environment requirements, resource mapping, and
  scheduler/container compatibility.
- Update feature docs and examples for named build targets, local build
  service, SIF build, direct Apptainer execution, SLURM composition, clean-env
  defaults, output refs, deferrals, and optional smoke tests.
- Add marked/manual opt-in smoke hooks for real Docker, Apptainer/Singularity,
  SIF build, and SLURM paths when available.

Out of scope:

- Requiring real runtimes, clusters, registries, fakeroot, or network in
  default validation.
- Adding registry/auth helpers, image publishing, external build services, or
  cleanup policy.

Acceptance criteria:

- Default `make validate-pr` remains fake/local/offline.
- Preflight is selected-executor scoped and stable enough for Stage 19
  reliability policy.
- Docs reflect the confirmed examples and design-safety guardrails.

Test expectations:

- Package: default import/CLI regressions.
- Unit: diagnostic model/check construction.
- Contract: stable check IDs, JSON output, and selected namespace behavior.
- Integration: fake preflight cases across build/direct/SLURM paths.
- E2E: default fake workflow coverage where repo patterns support it.
- Opt-in: real runtime/cluster smoke only under explicit markers or env gates.

Design impact:

- Turns implementation behavior into documented, diagnosable user workflows.

Future compatibility:

- Stage 19 can depend on stable diagnostic IDs and failure categories.

Alternatives rejected:

- Runtime-required CI, default network/fakeroot probes, and broad site-specific
  readiness policy.

Debt introduced:

- Real cluster/runtime evidence remains optional, so default validation proves
  contract shape rather than site integration.

Reviewability:

- Final cross-cutting phase is intentionally docs/diagnostics/test focused
  after core behavior is stable.

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | Roadmap framing, intent, capability triage, functionality agreement, and behavior baseline are confirmed. | pass | None. |
| Requirement-to-design traceability | Proposed implementation shape and DAQ-1 through DAQ-12 map confirmed requirements to design decisions. | pass | None. |
| Design-safety review completed | Passed on 2026-05-17 with no blockers; DAQ-12 upheld as auto-approved; guardrails recorded for merge semantics, output placement, SLURM build ordering, and Apptainer environment defaults. | pass | None. |
| Future-roadmap impact considered | Stage 19-21 touchpoints updated in the proposed implementation shape, design decisions, and design-safety findings. | pass | None. |
| Generic interface, adapter, and protocol flexibility considered | Shared `container_build`, runtime-specific builders, command runners, SLURM wrapping, and deferred path/rank/service boundaries are recorded and design-safety reviewed. | pass | None. |
| Example-to-validation traceability | Confirmed examples map to required fake/default validation, docs snippets, and optional smoke coverage. | pass | None. |
| Phase-shaping readiness | Five-phase implementation shape recorded with goals, scope, out-of-scope items, acceptance criteria, suite expectations, design impact, future compatibility, rejected alternatives, debt, and reviewability. | pass | None. |
| Unresolved blocked or needs-discussion functionality or design decisions | No unresolved high-impact `needs discussion` or `blocked` functionality or design decisions remain after design-safety review. | pass | None. |
| Final planning confirmation | User confirmed the functionality, behavior, code-structure, and usage explanation is good and asked to approve implementation-plan drafting. | pass | None. |

Readiness result:

- Status: implementation-plan draft created
- Implementation-plan drafting blockers:
  - None for the planning workflow.
- Drafting source refresh result:
  - Stage 17 expected shared container contracts were refreshed against the
    current checkout while drafting the implementation plan; Docker/shared
    container source modules are still absent and are recorded as an accepted
    risk in `docs/roadmap/stage-18/implementation-plan.md`.
- Accepted risks:
  - Stage 17 expected shared container contracts are not present in source in
    this checkout.
  - Explicit SIF build support is now in scope and its source boundary is
    confirmed. Design-safety review accepted this with fake/default-offline
    validation and explicit build-environment diagnostics.
  - Local-only build-service support is now confirmed; external/site build
    services are deferred.
  - Shared Docker/Apptainer dynamic build support is confirmed, but Stage 17
    Docker assumptions must be refreshed again before Phase 1 execution
    planning if Stage 17 lands after this draft; Stage 18 is selected as the
    owner for the shared/generic container-build phase.
- Assumptions to carry forward:
  - Design decisions have passed design-safety review and remain subject to
    Stage 17 source reconciliation during Phase 1 execution planning.
  - Stage 17 implementation assumptions must be refreshed against landed source
    before Phase 1 execution starts.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Do you have clarifying questions about the Stage 18 briefing before capability triage starts? | Roadmap framing | User asked and resolved clarifications about build service, shared build layer, and multi-node/rank orchestration. | closed |
| What should Stage 18 optimize for: direct Apptainer parity, SLURM plus Apptainer script/submission parity, fastest path to Stage 19 reliability compatibility, or another priority? | Roadmap framing and intent discovery | Build-once/reuse-across-stages container targets plus Apptainer-on-SLURM parity, while preserving Stage 19 reliability compatibility. | closed; user agreed |
| Who is the primary target user for Stage 18? | Roadmap framing and intent discovery | HPC pipeline authors and maintainers/operators who need inspectable local container-build records and SLURM-container jobs. | closed; user agreed |
| What exact `.sif` build sources should Stage 18 include? | Capability triage and functionality agreement | Include user-authored definition files and explicit source URIs/local sources through `apptainer build`; defer implicit conversion, auth helpers, and site build services. | closed; user agreed |
| How should the shared Docker/Apptainer build layer be sequenced with Stage 17 Docker work? | Phase shaping and adjacent-stage compatibility | Resolved direction: Stage 18 owns a shared/generic container-build phase and adapts Docker/Apptainer-specific semantics where required. The implementation-plan draft refreshed current source and found Stage 17 Docker/shared-container modules still absent; refresh again before Phase 1 execution planning and rerun design-safety only if Stage 17 changes shared contracts materially. | closed; user agreed |
| What does Stage 18's build service need to own? | Capability triage and design agreement | Resolved direction: local-only build request/result service for images/SIFs; external/site build services, Apptainer remote-build behavior, and registry/auth policy are deferred. | closed; user agreed |
| Is the Stage 18 planning artifact accepted as the source for implementation-plan drafting? | Final planning confirmation | Accepted after the user reviewed the functionality, behavior, code-structure, and usage explanation and asked to approve implementation-plan drafting. | closed; user confirmed |

## Handoff Notes

Implementation-plan draft inputs:

- Draft created at `docs/roadmap/stage-18/implementation-plan.md` from this
  confirmed planning artifact.
- The implementation plan preserves the design-safety guardrails recorded
  above and records Stage 17 source absence as an accepted risk.
- Before Phase 1 execution planning, refresh Stage 17 landed source
  assumptions again, especially shared container records and Docker executor
  contracts.

Design-safety review result:

- Passed on 2026-05-17 with no blockers or needs-discussion decisions. DAQ-12
  was upheld as auto-approved; DAQ-1 through DAQ-11 remain recorded
  recommendations. Guardrails were added for `container_build` replacement
  semantics, explicit build output refs, submit-side build ordering before
  SLURM rendering/submission, and Apptainer clean environment defaults.

Validation and phase-shaping inputs:

- Confirmed examples, validation obligations, and a five-phase implementation
  shape are recorded.

Plan-quality-gate risks:

- Stage 17 source/prerequisite assumptions may change before Stage 18
  implementation-plan drafting.
- SIF build support needs a careful boundary so Stage 18 does not become a
  registry, image-conversion, or site build-service stage.
- Build-service support is local-only for Stage 18 because current Apptainer
  does not provide the old remote-build path and the user deferred external/site
  build service adapters.
- Shared Docker/Apptainer build support is selected for Stage 18. The
  implementation-plan pass must refresh actual Stage 17 state, then plan a
  shared/generic container-build phase with Docker and Apptainer adapters.
- Public executor naming and SLURM-container composition surface are durable
  contract risks.
- Path parity, artifact visibility, and scheduler/container resource ownership
  remain implementation-plan risk areas, with design-safety guardrails now
  recorded.

Assumptions to carry forward:

- Apptainer/Singularity remains optional and CLI-backed.
- Stage 18 should preserve existing Loom worker, SLURM, store, provenance,
  diagnostics, and testing boundaries unless user feedback reopens that
  direction.
