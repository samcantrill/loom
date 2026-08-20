"""Trusted dummy stages for local execution tests."""

from __future__ import annotations

import time
import os
from collections.abc import Mapping
from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext


class JsonProducerStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        value = context.stage_config.get("value", 1)
        counter_path = context.stage_config.get("counter_path")
        if isinstance(counter_path, str):
            path = Path(counter_path)
            current = int(path.read_text(encoding="utf-8")) if path.exists() else 0
            path.write_text(str(current + 1), encoding="utf-8")
        return {
            "data": context.save_artifact(
                "data",
                {"value": value},
                artifact_type="json",
                codec_key="json.v1",
            )
        }


class ConfiguredProducerStage:
    def __init__(self, *, constructor_value: int) -> None:
        self.constructor_value = constructor_value

    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        return {
            "data": context.save_artifact(
                "data",
                {
                    "constructor": self.constructor_value,
                    "runtime": context.stage_config.get("runtime_value"),
                    "constructor_in_stage_config": "constructor_value"
                    in context.stage_config,
                },
                artifact_type="json",
                codec_key="json.v1",
            )
        }


class TextConsumerStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        data = context.load_input("data", expected_type="json")
        return {
            "text": context.save_artifact(
                "text",
                f"seen {data}",
                artifact_type="text",
                codec_key="text.v1",
            )
        }


class FailingStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        marker_path = context.stage_config.get("wait_for_marker")
        if isinstance(marker_path, str):
            raw_timeout_seconds = context.stage_config.get("timeout_seconds", 5)
            timeout_seconds = (
                float(raw_timeout_seconds)
                if isinstance(raw_timeout_seconds, int | float | str)
                else 5.0
            )
            deadline = time.monotonic() + timeout_seconds
            path = Path(marker_path)
            while not path.exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("failing stage timed out waiting for marker")
                time.sleep(0.01)
        raise RuntimeError("stage failed intentionally")


class FailOnceThenProduceStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        marker_path = Path(str(context.stage_config["marker_path"]))
        if not marker_path.exists():
            marker_path.write_text("failed-once", encoding="utf-8")
            raise RuntimeError("stage failed on first attempt")
        return {
            "data": context.save_artifact(
                "data",
                {"attempt": "retried"},
                artifact_type="json",
                codec_key="json.v1",
            )
        }


class EarlyStopStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        context.stop_early(
            str(context.stage_config.get("message", "stopped early")),
            detail={"stage": context.stage_name, "configured": True},
        )
        return {}


class KeyboardInterruptStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = context, inputs
        raise KeyboardInterrupt("stage interrupted intentionally")


class SleepStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        raw_seconds = context.stage_config.get("seconds", 30)
        seconds = (
            float(raw_seconds)
            if isinstance(raw_seconds, int | float | str)
            else 30.0
        )
        release_marker = context.stage_config.get("release_marker")
        if isinstance(release_marker, str) and Path(release_marker).exists():
            seconds = 0.0
        marker_path = context.stage_config.get("started_marker")
        if isinstance(marker_path, str):
            Path(marker_path).write_text(context.stage_name, encoding="utf-8")
        pid_marker = context.stage_config.get("pid_marker")
        if isinstance(pid_marker, str):
            Path(pid_marker).write_text(str(os.getpid()), encoding="utf-8")
        time.sleep(seconds)
        return {
            "data": context.save_artifact(
                "data",
                {"slept": seconds},
                artifact_type="json",
                codec_key="json.v1",
            )
        }


class ReleaseStage:
    """Test stage which waits for its fixture-owned release marker."""

    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        marker_dir = Path(str(context.stage_config["marker_dir"]))
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / f"{context.stage_name}.started").write_text(
            context.stage_name,
            encoding="utf-8",
        )
        timeout_seconds = float(context.stage_config.get("timeout_seconds", 10))
        deadline = time.monotonic() + timeout_seconds
        release = marker_dir / "release"
        while not release.exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("release stage timed out waiting for fixture")
            time.sleep(0.01)
        return {
            "data": context.save_artifact(
                "data",
                {"stage": context.stage_name},
                artifact_type="json",
                codec_key="json.v1",
            )
        }


class CoordinatedStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        marker_dir = Path(str(context.stage_config["marker_dir"]))
        raw_wait_for = context.stage_config.get("wait_for", 1)
        wait_for = (
            int(raw_wait_for) if isinstance(raw_wait_for, int | str) else 1
        )
        raw_timeout_seconds = context.stage_config.get("timeout_seconds", 5)
        timeout_seconds = (
            float(raw_timeout_seconds)
            if isinstance(raw_timeout_seconds, int | float | str)
            else 5.0
        )
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / f"{context.stage_name}.started").write_text(
            context.stage_name,
            encoding="utf-8",
        )
        deadline = time.monotonic() + timeout_seconds
        while len(list(marker_dir.glob("*.started"))) < wait_for:
            if time.monotonic() >= deadline:
                raise RuntimeError("coordinated stage timed out")
            time.sleep(0.01)
        return {
            "data": context.save_artifact(
                "data",
                {"stage": context.stage_name},
                artifact_type="json",
                codec_key="json.v1",
            )
        }


class BadOutputStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = context, inputs
        return {}


class NotAStage:
    pass
