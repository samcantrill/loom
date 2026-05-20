# Artifact-Safe Config Artifacts

This example uses the public `compose_config` and
`compare_config_artifact_fingerprints` APIs to inspect artifact-facing config
records without printing plaintext secrets.

It demonstrates:

- metadata-only source artifacts for base, overlay, and include YAML inputs;
- artifact-safe fingerprint comparison across different `oc.env` values;
- resolver facts that preserve authored `oc.env` expressions;
- secret redaction in artifact-facing views;
- default metadata-only raw source snapshot references;
- explicit opt-in raw source snapshot payloads, summarized without content.

## Public Python Surface

This example teaches `weave.compose_config` and
`compare_config_artifact_fingerprints`.

Run from the repository root:

```sh
uv run python packages/weave/examples/artifact-safety/artifact_safety.py
```
