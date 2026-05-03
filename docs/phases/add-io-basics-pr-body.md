## Phase

- Phase: Phase 3 - I/O Basics
- Branch: `codex/add-io-basics`
- Target: `develop`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-io-basics`
- Plan: `docs/implementation-plans/implementation-plan-v0.md`
- Expanded phase plan: `docs/phases/add-io-basics.md`

## Summary

Implements the Phase 3 I/O layer: URI parsing/normalization helpers, a
structural `DataSource` protocol with local filesystem support, structural
codec support with JSON/text/bytes codecs, codec-specific errors, and an
explicit instance-based `CodecRegistry`.

## Acceptance Criteria

- [x] Local paths and `file://` URIs round-trip correctly.
- [x] Local source supports `open`, `exists`, `stat`, `glob`, and path
  resolution.
- [x] JSON/text/bytes codecs round-trip supported values.
- [x] JSON codec rejects unsupported non-plain objects.
- [x] Codec registry rejects duplicate keys and unknown codec lookups.
- [x] Package, unit, contract, and integration tests cover the Phase 3 public
  surface.
- [x] E2E and opt-in suites are explicitly deferred by the expanded phase plan.

## Implementation Notes

The I/O layer remains standard-library only and domain-neutral. It keeps URI
parsing, local source access, and byte-oriented codecs separate from stores,
checksums, artifact layout, config, pipeline execution, and resume policy.

`create_default_codec_registry()` returns a fresh registry instance each time;
there is no mutable global registry, plugin discovery, source registry, remote
backend, or codec inference from file extensions. `loom.__init__` remains
unchanged so top-level imports stay cheap and do not pull in `loom.io`.

Accepted Phase 3 debt remains documented in the expanded phase plan: local
filesystem is the only source, unrooted relative resolution can depend on the
process current working directory, codecs are in-memory and byte-oriented, and
source registries/checksums/atomic persistence remain deferred to later phases.

## Tests And Validation

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright reported 0 errors, default pytest passed with 136 tests, and uv build produced source and wheel distributions.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md.
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 0.51s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 0.46s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | passed | 0.25s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | passed | 0.26s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | not present | 0.00s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

## PR Creation Status

The PR body is ready, but the PR was not opened because the branch could not be
pushed to GitHub from this environment.

```text
command: git push -u origin codex/add-io-basics
result: failed after network escalation; ssh_askpass: exec(/usr/bin/ssh-askpass): No such file or directory; git@github.com: Permission denied (publickey).; fatal: Could not read from remote repository.
```

```text
command: gh pr create --base develop --head codex/add-io-basics --title "Phase 3: I/O Basics" --body-file docs/phases/add-io-basics-pr-body.md
result: failed; pull request create failed: GraphQL: Head sha can't be blank, Base sha can't be blank, No commits between develop and codex/add-io-basics, Head ref must be a branch (createPullRequest).
```

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

## Risks / Follow-Ups

- Remote sources, source registries, artifact stores, checksums, atomic writes,
  run layout, config composition, pipeline execution, resume, CLI behavior, and
  domain codecs remain deferred to their owning phases.
- E2E and opt-in suites are deferred because Phase 3 has no runnable pipeline
  workflow, remote/network behavior, optional dependencies, SLURM, or slow-test
  scope.
- PR review budget remains unused; implementation refinement budget was used
  once by the bounded refinement pass.
- Remote PR creation remains blocked until the branch can be pushed or created
  on GitHub.
