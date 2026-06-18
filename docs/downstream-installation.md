# Downstream Installation And Release Process

This repository publishes `loom` from the repository root. `loom` depends on
`weave` for supported authored-config workflows, and this checkout resolves
`weave` from `https://github.com/samcantrill/weave`.

## Local Repository Setup

Install the repository for development from the root:

```sh
uv sync --all-groups
uv run python -c "import loom, weave"
uv run loom --help
```

`uv run` and `uv sync` operate on the root `loom` package. The `weave` package
is not a workspace member in this repository; it is resolved through the Git
source declared in `pyproject.toml` and pinned in `uv.lock`.

## Downstream uv Dependency

For a downstream project that needs Loom for experiment execution, workflows,
artifacts, sweeps, or config infrastructure, prefer an optional extra:

```toml
[project.optional-dependencies]
loom = [
    "loom",
]

[tool.uv.sources]
loom = { git = "ssh://git@github.com/<org>/loom.git", tag = "v0.1.0" }
weave = { git = "https://github.com/samcantrill/weave.git", rev = "<full-commit-sha>" }
```

Install it with:

```sh
uv sync --extra loom
uv run python -c "import loom, weave"
```

If `loom` is required for normal runtime imports, put it in the normal
dependency list instead. Keep the `weave` source pinned to a tag or full commit
SHA for reproducibility.

## Local Downstream Development

When changing Loom and a downstream project together, use an editable local path
source for Loom and a separate local path or Git source for `weave`:

```toml
[tool.uv.sources]
loom = { path = "../loom", editable = true }
weave = { path = "../weave", editable = true }
```

Return to Git refs before committing downstream release or CI changes.

## Private Repository Access

For local development, SSH access is usually simplest:

```sh
ssh -T git@github.com
```

For CI, configure one of:

- A read-only deploy key for the required private repositories.
- A GitHub App token with repository read access.
- A fine-grained personal access token stored as a CI secret.

Do not put tokens directly in `pyproject.toml`, `uv.lock`, requirements files,
or committed CI logs.

## Loom Release Checklist

Use this checklist when publishing a tag for downstream projects.

1. Merge the intended changes to the release branch.
2. Update the root `pyproject.toml` version.
3. Run `uv lock`.
4. Run `make validate-pr`.
5. Run `make test-summary`.
6. Build the package with `make build`.
7. Commit the version and lockfile changes.
8. Create and push an annotated tag:

   ```sh
   git tag -a v0.1.1 -m "v0.1.1"
   git push origin v0.1.1
   ```

9. Smoke-test a clean install from the tag:

   ```sh
   uv venv /tmp/loom-release-smoke
   uv pip install --python /tmp/loom-release-smoke/bin/python        "loom @ git+ssh://git@github.com/<org>/loom.git@v0.1.1"
   /tmp/loom-release-smoke/bin/python -c "import loom, weave"
   ```

Do not move a published tag. Create a new patch tag for fixes.

## Downstream Update Checklist

Use this checklist in each downstream project.

1. Update the `loom` and `weave` Git refs to the intended tags or full commit SHAs.
2. Run `uv lock`.
3. Run `uv sync --extra loom`, or plain `uv sync` when `loom` is a normal dependency.
4. Run the downstream test suite and any representative workflow smoke tests.
5. Commit `pyproject.toml` and `uv.lock` together.

If CI cannot resolve the private Git dependency, fix repository access through
SSH keys or token-backed Git credentials. Do not work around CI by committing
credentials into dependency metadata.
