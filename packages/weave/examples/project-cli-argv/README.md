# Project CLI Argv Shorthand

This example shows how a project-owned CLI can pass argv fragments to
`weave.compose_config_from_argv`.

`weave` does not provide a first-party CLI executable. The project CLI owns its
commands and command-specific flags; `weave` only parses config shorthand and
returns unparsed command arguments to the caller when requested.

It demonstrates:

- `<command> <base-config> ...` argv shape;
- trailing-slash scoped overlays such as `data/=data_A`;
- `+scope/=` scoped overlay creation for missing config sections;
- ordinary dot-path value overrides that apply after scoped overlays;
- helper-local warnings for likely missing scoped-overlay slashes;
- command-specific passthrough args returned with `allow_unparsed=True`.

## Run

Run from the repository root:

```sh
uv run python packages/weave/examples/project-cli-argv/project_cli_argv.py
```
