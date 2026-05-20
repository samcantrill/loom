"""Compose trusted local YAML includes with public include overrides."""

from __future__ import annotations

from pathlib import Path
from pprint import pprint
from typing import cast

from weave import ComposedConfig, compose_config
from weave.plain import PlainData


HERE = Path(__file__).resolve().parent
CONFIG_ROOT = HERE / "configs"


def _mapping(value: object) -> dict[str, PlainData]:
    assert isinstance(value, dict)
    return cast(dict[str, PlainData], value)


def main() -> None:
    authored = compose_config(CONFIG_ROOT / "base.yaml")
    authored_pipeline = _mapping(authored.resolved["pipeline"])
    authored_processor = _mapping(authored_pipeline["processor"])
    authored_engine = _mapping(authored_processor["engine"])

    assert authored_processor["kind"] == "baseline"
    assert authored_processor["batch_size"] == 64
    assert authored_engine == {"name": "simple-engine", "parallelism": 2}

    user_composed = compose_config(
        CONFIG_ROOT / "base.yaml",
        overrides=(
            "pipeline.processor._include_=./components/processor/replacement.yaml",
            "+pipeline.sink._include_=./components/sink/local.yaml",
        ),
    )

    pipeline = _mapping(user_composed.resolved["pipeline"])
    processor = _mapping(pipeline["processor"])
    engine = _mapping(processor["engine"])
    labels = _mapping(processor["labels"])
    sink = _mapping(pipeline["sink"])

    assert processor["kind"] == "replacement"
    assert processor["batch_size"] == 64
    assert engine["name"] == "parallel-engine"
    assert labels == {"tier": "replacement", "owner": "config-example"}
    assert sink == {"kind": "local-log", "format": "json", "retention_days": 7}

    authored_include_artifacts = _include_artifacts(authored)
    user_include_artifacts = _include_artifacts(user_composed)

    print("authored include fingerprint:")
    print(f"  {authored.fingerprint}")
    print("authored include source artifacts:")
    pprint(authored_include_artifacts, sort_dicts=True)
    print("user-composed fingerprint:")
    print(f"  {user_composed.fingerprint}")
    print("user-composed resolved pipeline:")
    pprint(pipeline, sort_dicts=True)
    print("user-composed include source artifacts:")
    pprint(user_include_artifacts, sort_dicts=True)


def _include_artifacts(composed: ComposedConfig) -> list[dict[str, object]]:
    return [
        {
            "path": Path(artifact.path).relative_to(CONFIG_ROOT).as_posix(),
            "site": artifact.metadata["include_site_path"],
            "authored_target": artifact.metadata["authored_target"],
        }
        for artifact in composed.source_artifacts
        if artifact.kind == "include"
    ]


if __name__ == "__main__":
    main()
