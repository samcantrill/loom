# Downstream Installation And Release Process

This repository currently publishes two installable packages from one Git
repository:

- `loom`, from the repository root.
- `weave`, from `packages/weave`.

`loom` depends on `weave` for supported authored-config workflows. Because
`weave` is a separate package and is not assumed to be available on a public
package index, downstream uv projects should declare sources for both packages.
Pin both sources to the same tag or commit. `tool.uv.sources` is uv-specific;
if a downstream project uses another installer, repeat the same direct Git URL
requirements in that tool's supported format.

## Local Repository Setup

Install the repository for development from the root:

```sh
uv sync --all-groups
uv run python -c "import loom, weave"
uv run loom --help
```

The root `pyproject.toml` declares `packages/weave` as a uv workspace member so
the repository uses one lockfile for the root package and bundled `weave`
package. `uv run` and `uv sync` operate on the root package by default.

Run commands against `weave` directly with:

```sh
uv run --package weave python -c "import weave"
```

## Downstream uv Dependency

For a downstream project that needs Loom only for experiment execution,
workflows, artifacts, sweeps, or config infrastructure, prefer an optional
extra:

```toml
[project.optional-dependencies]
loom = [
    "loom",
    "weave",
]

[tool.uv.sources]
loom = { git = "ssh://git@github.com/<org>/loom.git", tag = "v0.1.0" }
weave = { git = "ssh://git@github.com/<org>/loom.git", tag = "v0.1.0", subdirectory = "packages/weave" }
```

Install it with:

```sh
uv sync --extra loom
uv run python -c "import loom, weave"
```

If `loom` and `weave` are required for normal runtime imports, put both packages
in the normal dependency list instead:

```toml
[project]
dependencies = [
    "loom",
    "weave",
]

[tool.uv.sources]
loom = { git = "ssh://git@github.com/<org>/loom.git", tag = "v0.1.0" }
weave = { git = "ssh://git@github.com/<org>/loom.git", tag = "v0.1.0", subdirectory = "packages/weave" }
```

For the strictest reproducibility, replace `tag = "v0.1.0"` with a full commit
SHA:

```toml
[tool.uv.sources]
loom = { git = "ssh://git@github.com/<org>/loom.git", rev = "<full-commit-sha>" }
weave = { git = "ssh://git@github.com/<org>/loom.git", rev = "<full-commit-sha>", subdirectory = "packages/weave" }
```

Avoid pinning to a moving branch such as `main` or `develop`.

## Local Downstream Development

When changing Loom and a downstream project together, use editable local path
sources in the downstream project:

```toml
[tool.uv.sources]
loom = { path = "../loom", editable = true }
weave = { path = "../loom/packages/weave", editable = true }
```

Return to Git refs before committing downstream release or CI changes.

## Private Repository Access

For local development, SSH access is usually simplest:

```sh
ssh -T git@github.com
```

For CI, configure one of:

- A read-only deploy key for this repository.
- A GitHub App token with repository read access.
- A fine-grained personal access token stored as a CI secret.

Do not put tokens directly in `pyproject.toml`, `uv.lock`, requirements files,
or committed CI logs.

## Loom Release Checklist

Use this checklist when publishing a tag for downstream projects.

1. Merge the intended changes to the release branch.
2. Update the root `pyproject.toml` version and `packages/weave/pyproject.toml`
   version together while the packages are released from the same private repo.
3. Run `uv lock`.
4. Run `make validate-pr`.
5. Run `make test-summary`.
6. Build the packages with `make build`.
7. Commit the version and lockfile changes.
8. Create and push an annotated tag:

   ```sh
   git tag -a v0.1.1 -m "v0.1.1"
   git push origin v0.1.1
   ```

9. Smoke-test a clean install from the tag:

   ```sh
   uv venv /tmp/loom-release-smoke
   uv pip install --python /tmp/loom-release-smoke/bin/python \
       "weave @ git+ssh://git@github.com/<org>/loom.git@v0.1.1#subdirectory=packages/weave" \
       "loom @ git+ssh://git@github.com/<org>/loom.git@v0.1.1"
   /tmp/loom-release-smoke/bin/python -c "import loom, weave"
   ```

Do not move a published tag. Create a new patch tag for fixes.

## Downstream Update Checklist

Use this checklist in each downstream project.

1. Update both `loom` and `weave` entries in `[tool.uv.sources]` to the same tag
   or full commit SHA.
2. Run `uv lock`.
3. Run `uv sync --extra loom`, or plain `uv sync` when `loom` and `weave` are
   normal dependencies.
4. Run the downstream test suite and any representative workflow smoke tests.
5. Commit `pyproject.toml` and `uv.lock` together.

If CI cannot resolve the private Git dependency, fix repository access through
SSH keys or token-backed Git credentials. Do not work around CI by committing
credentials into dependency metadata.
