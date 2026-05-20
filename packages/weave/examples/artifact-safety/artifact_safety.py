"""Inspect artifact-safe configuration metadata without printing secrets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from weave import ComposedConfig, compare_config_artifact_fingerprints, compose_config


HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
BASE = INPUTS / "base.yaml"
OVERLAY = INPUTS / "overlay.yaml"


def _compose(*, token: str, raw_snapshots: bool = False) -> ComposedConfig:
    os.environ["LOOM_ARTIFACT_SAFETY_TOKEN"] = token
    os.environ["LOOM_ARTIFACT_SAFETY_ENDPOINT"] = "https://runtime.example/api"
    os.environ["LOOM_ARTIFACT_SAFETY_OUTPUT"] = "/tmp/loom-artifact-safety"
    return compose_config(
        BASE,
        overlays=(OVERLAY,),
        include_raw_source_snapshots=raw_snapshots,
    )


def _resolver_facts(composed: ComposedConfig) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], composed.provenance.metadata["resolver_records"])


def main() -> None:
    first = _compose(token="alpha-secret-value")
    second = _compose(token="beta-secret-value")
    with_snapshots = _compose(token="alpha-secret-value", raw_snapshots=True)

    env_change = compare_config_artifact_fingerprints(first.manifest, second.manifest)
    snapshot_change = compare_config_artifact_fingerprints(first.manifest, with_snapshots.manifest)

    print("artifact-safe fingerprint comparison:")
    print(f"  env value changed: {env_change.status} ({env_change.reason})")
    print(f"  raw snapshots opted in: {snapshot_change.status} ({snapshot_change.reason})")

    print("source artifacts:")
    for artifact in first.source_artifacts:
        print(
            "  "
            f"{artifact.order}: {artifact.kind} "
            f"size={artifact.size_bytes} "
            f"digest={artifact.content_digest[:12]}..."
        )

    print("resolver facts:")
    for fact in _resolver_facts(first):
        print(f"  {fact['config_path']}: {fact['resolver']} -> {fact['token']}")

    redacted_service = cast(dict[str, Any], first.redacted["pipeline"])["service"]
    resolved_service = cast(dict[str, Any], first.resolved["pipeline"])["service"]
    print("secret handling:")
    print(f"  redacted api_token: {cast(dict[str, Any], redacted_service)['api_token']}")
    print(f"  resolved api_token present: {'api_token' in cast(dict[str, Any], resolved_service)}")

    default_refs = first.raw_source_snapshots.references
    opt_in_refs = with_snapshots.raw_source_snapshots.references
    print("raw source snapshots:")
    print(
        "  default: "
        f"enabled={first.raw_source_snapshots.enabled} "
        f"payloads={len(first.raw_source_snapshots.payloads)} "
        f"availability={[reference.availability for reference in default_refs]}"
    )
    print(
        "  opt-in: "
        f"enabled={with_snapshots.raw_source_snapshots.enabled} "
        f"payloads={len(with_snapshots.raw_source_snapshots.payloads)} "
        f"availability={[reference.availability for reference in opt_in_refs]}"
    )
    for payload in with_snapshots.raw_source_snapshots.payloads:
        print(
            "  payload: "
            f"size={payload.size_bytes} "
            f"digest={payload.content_digest[:12]}... "
            "content=<not printed>"
        )


if __name__ == "__main__":
    main()
