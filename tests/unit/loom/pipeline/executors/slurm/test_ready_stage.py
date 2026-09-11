from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Event
from typing import cast

import pytest

from loom.pipeline.executors.containers import ContainerOptions
from loom.pipeline.executors.slurm.commands import (
    FakeSlurmCommandRunner,
    SlurmCommandResult,
)

from loom.pipeline.executors.slurm.errors import (
    SlurmPlanningError,
    SlurmResourceMappingError,
)
from loom.pipeline.executors.slurm.ready_stage import (
    ReadyStageState,
    SQLiteReadyStageSubmissions,
    SlurmJobPrivateFileProvider,
    SlurmReadyStageProfile,
    SlurmReadyStageSubmission,
    map_ready_stage,
    operation_marker,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.runtime import (
    CpuResourcePlanner,
    ExecutionRoute,
    ExecutionRouteKind,
    StagePlacementPolicy,
    resolve_stage_placement,
)
from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.serialization import stable_json_dumps

_TEST_HELPER = (
    sys.executable,
    str(Path(__file__).parents[5] / "support" / "slurm_job_private_helper.py"),
)


def _profile(
    runner: FakeSlurmCommandRunner,
    *,
    credential_reference: str = "slurm-credential",
    available: bool = True,
    cluster: str | None = "cluster-a",
    provider: SlurmJobPrivateFileProvider | None = None,
    container_options: dict[str, object] | None = None,
) -> SlurmReadyStageProfile:
    return SlurmReadyStageProfile(
        profile_id="training",
        partition="gpu",
        max_outstanding=1,
        bootstrap_argv=("loom", "slurm-bootstrap"),
        runner=runner,
        command_adapter_fingerprint="fake-slurm-v1",
        bootstrap_principal_id="slurm-principal",
        credential_reference=credential_reference,
        coordinator_endpoint="https://coordinator.example",
        project_fingerprint="project-v1",
        environment_fingerprint="environment-v1",
        executor_fingerprint="executor-v1",
        job_private_file_provider=provider
        or SlurmJobPrivateFileProvider(
            fixed_path="/tmp/loom-unit-capability",
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
        container_options=container_options,
        cluster=cluster,
        available=available,
    )


def _ready_container_options() -> dict[str, object]:
    return {
        "image": {"reference": "analysis.sif"},
        "mounts": [
            {
                "source": "/tmp/loom-unit-capability",
                "target": "/tmp/loom-unit-capability",
                "mode": "rw",
            }
        ],
        "environment": {
            "required_host_variables": ["LOOM_SLURM_BOOTSTRAP_CONFIG"],
        },
    }


def _request(
    profile: SlurmReadyStageProfile,
    *,
    resources: ResourceRequest | None = None,
):  # type: ignore[no-untyped-def]
    placement = resolve_stage_placement(
        authored=(
            ResourceRequest(entries={"cpu": ResourceEntry("cpu", 2, "count")})
            if resources is None
            else resources
        ),
        runtime=None,
        policy=StagePlacementPolicy(
            route=ExecutionRoute(
                kind=ExecutionRouteKind.SLURM,
                profile_id=profile.profile_id,
                profile_descriptor=profile.descriptor,
                profile_configuration_fingerprint=profile.configuration_fingerprint,
            )
        ),
        planners={"cpu": CpuResourcePlanner(), "gpu": GpuResourcePlanner()},
    )
    return map_ready_stage(
        placement=placement,
        profile=profile,
        operation_id="operation-1",
        stage_work_id="work-1",
        run_uri="runs/example",
        attempt_id="attempt-1",
    )


def _script(tmp_path: Path, request) -> Path:  # type: ignore[no-untyped-def]
    path = tmp_path / "bootstrap.sh"
    path.write_text(request.script, encoding="utf-8")
    return path


def test_ready_stage_script_is_fixed_safe_and_deterministic() -> None:
    profile = _profile(FakeSlurmCommandRunner())
    request = _request(profile)

    assert request == _request(profile)
    assert f"#SBATCH --comment={operation_marker('operation-1')}" in request.script
    assert "exec 'loom' 'slurm-bootstrap'" in request.script
    assert f"--request-digest '{request.digest}'" in request.script
    assert "runs/example" not in request.script
    assert profile.credential_reference not in request.script
    assert "capability" not in request.script
    assert request.schema_version == 3
    assert request.container_metadata is None
    assert type(request).from_dict(request.to_dict()) == request

    with pytest.raises(SlurmPlanningError, match="fixed Loom bootstrap"):
        SlurmReadyStageProfile(
            profile_id="training",
            partition="gpu",
            max_outstanding=1,
            bootstrap_argv=("/tmp/loom", "slurm-bootstrap"),
            runner=FakeSlurmCommandRunner(),
            command_adapter_fingerprint="fake-slurm-v1",
            bootstrap_principal_id="slurm-principal",
            credential_reference="slurm-credential",
            coordinator_endpoint="https://coordinator.example",
            project_fingerprint="project-v1",
            environment_fingerprint="environment-v1",
            executor_fingerprint="executor-v1",
            job_private_file_provider=SlurmJobPrivateFileProvider(
                fixed_path="/tmp/loom-unit-capability",
                descriptor="fake-prolog-v1",
                helper_argv=_TEST_HELPER,
            ),
        )


def test_retained_native_profile_uses_the_prior_identity_payload() -> None:
    profile = _profile(FakeSlurmCommandRunner())
    provider = profile.job_private_file_provider
    legacy_payload = {
        "profile_id": profile.profile_id,
        "partition": profile.partition,
        "account": profile.account,
        "qos": profile.qos,
        "cluster": profile.cluster,
        "max_outstanding": profile.max_outstanding,
        "bootstrap_argv": list(profile.bootstrap_argv),
        "command_adapter_fingerprint": profile.command_adapter_fingerprint,
        "bootstrap_principal_id": profile.bootstrap_principal_id,
        "credential_reference_digest": hashlib.sha256(
            profile.credential_reference.encode("utf-8")
        ).hexdigest(),
        "coordinator_endpoint_digest": hashlib.sha256(
            profile.coordinator_endpoint.encode("utf-8")
        ).hexdigest(),
        "project_fingerprint": profile.project_fingerprint,
        "environment_fingerprint": profile.environment_fingerprint,
        "executor_fingerprint": profile.executor_fingerprint,
        "executor_name": profile.executor_name,
        "credential_policy_revision": profile.credential_policy_revision,
        "capability_delivery_kind": provider.delivery_kind,
        "capability_descriptor": provider.descriptor,
        "capability_path": provider.fixed_path,
        "containment_helper_descriptor": None,
        "containment_helper_argv": None,
        "containment_helper_timeout_seconds": None,
    }

    assert (
        profile.configuration_fingerprint
        == hashlib.sha256(stable_json_dumps(legacy_payload).encode("utf-8")).hexdigest()
    )


def test_ready_stage_selected_container_wraps_fixed_bootstrap_and_retains_receipt(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, container_options=_ready_container_options())
    request = _request(profile)
    replay = _request(profile)

    assert request == replay
    assert request.schema_version == 4
    assert request.container_metadata is not None
    assert "exec 'apptainer' 'exec' '--cleanenv'" in request.script
    assert "'analysis.sif' 'loom' 'slurm-bootstrap'" in request.script
    assert (
        '"${LOOM_SLURM_BOOTSTRAP_CONFIG:?ready-stage container bootstrap config is unavailable}"'
        in request.script
    )
    assert (
        'export APPTAINERENV_LOOM_SLURM_BOOTSTRAP_CONFIG="${LOOM_SLURM_BOOTSTRAP_CONFIG}"'
        in request.script
    )
    assert "/tmp/loom-unit-capability" not in repr(request.container_metadata)
    assert request.container_metadata["container_runtime"] == "apptainer"
    assert request.container_metadata["bootstrap_environment"] == (
        "LOOM_SLURM_BOOTSTRAP_CONFIG"
    )
    assert type(request).from_dict(request.to_dict()) == request

    changed = _profile(
        FakeSlurmCommandRunner(),
        container_options={
            **_ready_container_options(),
            "image": {"reference": "analysis-next.sif"},
        },
    )
    assert changed.configuration_fingerprint != profile.configuration_fingerprint
    assert _request(changed).digest != request.digest

    changed_environment = _profile(
        FakeSlurmCommandRunner(),
        container_options={
            **_ready_container_options(),
            "environment": {
                "variables": {"ANALYSIS_MODE": "replay"},
                "required_host_variables": ["LOOM_SLURM_BOOTSTRAP_CONFIG"],
            },
        },
    )
    assert (
        changed_environment.configuration_fingerprint
        != profile.configuration_fingerprint
    )

    accepted = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite").submit(
        request, profile, _script(tmp_path, request)
    )
    assert accepted.state is ReadyStageState.ACCEPTED
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1


@pytest.mark.parametrize(
    ("runtime_name", "bootstrap_prefix"),
    (("apptainer", "APPTAINERENV"), ("singularity", "SINGULARITYENV")),
)
def test_ready_stage_container_bootstrap_env_reaches_rendered_runtime(
    tmp_path: Path, runtime_name: str, bootstrap_prefix: str
) -> None:
    profile = replace(
        _profile(
            FakeSlurmCommandRunner(), container_options=_ready_container_options()
        ),
        apptainer_options={"command": runtime_name},
    )
    request = _request(profile)
    script = _script(tmp_path, request)
    capture = tmp_path / "bootstrap-env"
    runtime = tmp_path / runtime_name
    runtime.write_text(
        f'#!/bin/sh\nprintf \'%s\' "${bootstrap_prefix}_LOOM_SLURM_BOOTSTRAP_CONFIG" > "$LOOM_TEST_CAPTURE"\n',
        encoding="utf-8",
    )
    runtime.chmod(0o755)

    subprocess.run(
        ["bash", str(script)],
        check=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "LOOM_SLURM_BOOTSTRAP_CONFIG": "/fixture/bootstrap.json",
            "LOOM_TEST_CAPTURE": str(capture),
        },
    )

    assert capture.read_text(encoding="utf-8") == "/fixture/bootstrap.json"


@pytest.mark.parametrize(
    ("visible", "expected_returncode"),
    (("GPU-allocated", 0), (None, 78), ("GPU-a,GPU-b", 78)),
)
def test_ready_stage_gpu_admission_runs_before_selected_container(
    tmp_path: Path, visible: str | None, expected_returncode: int
) -> None:
    profile = _profile(
        FakeSlurmCommandRunner(), container_options=_ready_container_options()
    )
    request = _request(
        profile,
        resources=ResourceRequest(
            entries={
                "gpu": ResourceEntry(
                    "gpu", 1, "count", {"allocation_mode": "exclusive"}
                )
            }
        ),
    )
    runtime = tmp_path / "apptainer"
    runtime.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    runtime.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "LOOM_SLURM_BOOTSTRAP_CONFIG": "/fixture/bootstrap.json",
    }
    if visible is None:
        environment.pop("CUDA_VISIBLE_DEVICES", None)
    else:
        environment["CUDA_VISIBLE_DEVICES"] = visible

    result = subprocess.run(
        ["bash", str(_script(tmp_path, request))],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == expected_returncode, result.stderr
    assert request.container_metadata is not None
    assert request.container_metadata["gpu_visibility"] == {
        "requested_gpu_count": 1,
        "visible_gpu_count": None,
    }


def test_ready_stage_container_receipt_redacts_absolute_owner_paths() -> None:
    provider = SlurmJobPrivateFileProvider(
        fixed_path="/private/owner/capability",
        descriptor="fake-prolog-v1",
        helper_argv=_TEST_HELPER,
    )
    profile = replace(
        _profile(
            FakeSlurmCommandRunner(),
            provider=provider,
            container_options={
                "image": {"reference": "/private/owner/image.sif"},
                "workdir": "/private/owner/workdir",
                "mounts": [
                    {
                        "source": "/private/owner/capability",
                        "target": "/private/owner/capability",
                        "mode": "rw",
                    }
                ],
                "environment": {
                    "required_host_variables": ["LOOM_SLURM_BOOTSTRAP_CONFIG"]
                },
            },
        ),
        apptainer_options={"command": "/private/owner/apptainer"},
    )
    request = _request(profile)

    assert request.container_metadata is not None
    receipt = stable_json_dumps(request.container_metadata)
    assert "/private/owner" not in receipt
    command = request.container_metadata["container_command"]
    assert command["command"] == "[redacted-path]"
    container = command["container"]
    assert container["image"] == "[redacted-path]"
    assert container["workdir"] == "[redacted-path]"
    assert container["mounts"] == [
        {"source": "[redacted-path]", "target": "[redacted-path]", "mode": "rw"}
    ]


def test_ready_stage_profile_accepts_typed_container_options_after_replace() -> None:
    profile = _profile(
        FakeSlurmCommandRunner(), container_options=_ready_container_options()
    )
    assert isinstance(profile.container_options, ContainerOptions)

    replaced = replace(profile)

    assert isinstance(replaced.container_options, ContainerOptions)
    assert replaced.configuration_fingerprint == profile.configuration_fingerprint


@pytest.mark.parametrize(
    ("container_options", "message"),
    [
        (
            {"image": {"reference": "analysis.sif"}},
            "bootstrap config environment",
        ),
        (
            {
                "image": {"reference": "analysis.sif"},
                "environment": {
                    "required_host_variables": ["LOOM_SLURM_BOOTSTRAP_CONFIG"]
                },
            },
            "writable capability path",
        ),
        (
            {
                "image": {"reference": "analysis.sif"},
                "mounts": [
                    {
                        "source": "/tmp/loom-unit-capability",
                        "target": "/tmp/loom-unit-capability",
                        "mode": "rw",
                    }
                ],
                "environment": {
                    "variables": {
                        "LOOM_SLURM_BOOTSTRAP_CONFIG": "/private/bootstrap.json"
                    },
                    "required_host_variables": ["LOOM_SLURM_BOOTSTRAP_CONFIG"],
                },
            },
            "cannot persist",
        ),
    ],
)
def test_ready_stage_container_rejects_missing_or_persisted_bootstrap_delivery(
    container_options: dict[str, object], message: str
) -> None:
    with pytest.raises(SlurmPlanningError, match=message):
        _profile(FakeSlurmCommandRunner(), container_options=container_options)


def test_job_private_provider_requires_a_concrete_site_helper() -> None:
    with pytest.raises(SlurmPlanningError, match="helper"):
        SlurmJobPrivateFileProvider(
            fixed_path="/tmp/capability", descriptor="site-helper", helper_argv=()
        )


def test_job_private_helper_is_verifier_only_and_replays_across_fresh_provider() -> (
    None
):
    first = SlurmJobPrivateFileProvider(
        fixed_path="/tmp/loom-unit-capability-replay",
        descriptor="fake-prolog-v1",
        helper_argv=_TEST_HELPER,
    )
    prepared = first.prepare(operation_id="operation-1", request_digest="digest-1")
    second = SlurmJobPrivateFileProvider(
        fixed_path="/tmp/loom-unit-capability-replay",
        descriptor="fake-prolog-v1",
        helper_argv=_TEST_HELPER,
    )

    assert (
        second.prepare(operation_id="operation-1", request_digest="digest-1")
        == prepared
    )
    assert not hasattr(first, "test_secret")
    assert not hasattr(first, "_prepared")
    material = Path(first.fixed_path).read_bytes()
    assert hashlib.sha256(material).hexdigest() == prepared.verifier
    assert material.hex() not in repr(prepared)


def test_indeterminate_or_conflicting_helper_result_never_reaches_sbatch(
    tmp_path: Path,
) -> None:
    unavailable = SlurmJobPrivateFileProvider(
        fixed_path=str(tmp_path / "capability"),
        descriptor="fake-prolog-v1",
        helper_argv=("/bin/false",),
    )
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, provider=unavailable)
    request = _request(profile)

    with pytest.raises(SlurmPlanningError, match="helper"):
        SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite").submit(
            request, profile, _script(tmp_path, request)
        )
    assert not [call for call in runner.calls if call[0] == "sbatch"]

    conflicting = SlurmJobPrivateFileProvider(
        fixed_path=str(tmp_path / "capability"),
        descriptor="fake-prolog-v1",
        helper_argv=(sys.executable, "-c", "print('{}')"),
    )
    conflict_runner = FakeSlurmCommandRunner()
    conflict_profile = _profile(conflict_runner, provider=conflicting)
    conflict_request = _request(conflict_profile)
    with pytest.raises(SlurmPlanningError, match="helper"):
        SQLiteReadyStageSubmissions(tmp_path / "conflict.sqlite").submit(
            conflict_request, conflict_profile, _script(tmp_path, conflict_request)
        )
    assert not [call for call in conflict_runner.calls if call[0] == "sbatch"]


def test_definite_submit_rejection_retains_site_material_for_release_owner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "capability"
    provider = SlurmJobPrivateFileProvider(
        fixed_path=str(path), descriptor="fake-prolog-v1", helper_argv=_TEST_HELPER
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [SlurmCommandResult("sbatch", ("sbatch",), 1)]}
    )
    profile = _profile(runner, provider=provider)
    request = _request(profile)

    result = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite").submit(
        request, profile, _script(tmp_path, request)
    )
    assert result.state is ReadyStageState.REJECTED
    assert path.exists()


def test_ready_stage_submit_uses_explicit_environment_and_export_nil(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")

    store.submit(request, profile, _script(tmp_path, request))

    sbatch_call = next(call for call in runner.calls if call[0] == "sbatch")
    assert "--export=NIL" in sbatch_call[1]
    assert runner.environments == [{}]


def test_ready_stage_publishes_the_submit_barrier_before_runner(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    barriers: list[SlurmReadyStageSubmission] = []

    def assert_barrier(value: SlurmReadyStageSubmission) -> None:
        assert not runner.calls
        barriers.append(value)

    result = store.submit(
        request,
        profile,
        _script(tmp_path, request),
        before_runner=assert_barrier,
    )

    assert result.state is ReadyStageState.ACCEPTED
    assert len(barriers) == 1
    assert barriers[0].state is ReadyStageState.SUBMITTING
    assert barriers[0].capability is not None
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1


def test_ready_stage_can_suppress_sbatch_at_the_final_submit_barrier(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")

    result = store.submit(
        request,
        profile,
        _script(tmp_path, request),
        before_runner=lambda submitting: False,
    )

    assert result.state is ReadyStageState.REJECTED
    assert result.evidence == "slurm_submit_suppressed_before_call"
    assert not [call for call in runner.calls if call[0] == "sbatch"]
    assert store.read(request.operation_id) == result


def test_ready_stage_hard_cut_rejects_prior_wire_and_store_versions(
    tmp_path: Path,
) -> None:
    profile = _profile(FakeSlurmCommandRunner())
    request = _request(profile)
    for version in (1, 2):
        with pytest.raises(SlurmPlanningError, match="schema"):
            type(request).from_dict({**request.to_dict(), "schema_version": version})

    path = tmp_path / "submissions.sqlite"
    SQLiteReadyStageSubmissions(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        conn.execute("PRAGMA user_version = 2")
    with pytest.raises(SlurmPlanningError, match="store is unsupported"):
        SQLiteReadyStageSubmissions(path, _allow_initialize=False)._open_existing()


def test_fresh_submission_store_never_reprepares_or_resubmits_after_submitting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    path = tmp_path / "submissions.sqlite"
    first = SQLiteReadyStageSubmissions(path)
    original_compare_and_set = SQLiteReadyStageSubmissions._compare_and_set

    def crash_after_submitting(
        owner: SQLiteReadyStageSubmissions,
        operation_id: str,
        *,
        expected: ReadyStageState,
        value: SlurmReadyStageSubmission,
    ) -> SlurmReadyStageSubmission:
        result = original_compare_and_set(
            owner, operation_id, expected=expected, value=value
        )
        if value.state is ReadyStageState.SUBMITTING:
            raise OSError("crash after durable submitting")
        return result

    monkeypatch.setattr(
        SQLiteReadyStageSubmissions, "_compare_and_set", crash_after_submitting
    )
    with pytest.raises(OSError, match="durable submitting"):
        first.submit(request, profile, _script(tmp_path, request))

    class FailingProvider(SlurmJobPrivateFileProvider):
        def prepare(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("must not prepare")

    reopened_profile = replace(
        profile,
        job_private_file_provider=FailingProvider(
            fixed_path="/tmp/loom-unit-capability",
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
    )
    reopened = SQLiteReadyStageSubmissions(path, _allow_initialize=False)
    sentinel_runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [AssertionError("must not submit")]}
    )
    reopened_profile = replace(reopened_profile, runner=sentinel_runner)
    assert (
        reopened.submit(request, reopened_profile, _script(tmp_path, request)).state
        is ReadyStageState.SUBMITTING
    )
    assert not [call for call in sentinel_runner.calls if call[0] == "sbatch"]


def test_fresh_store_submits_retained_prepared_receipt_without_reprepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_runner = FakeSlurmCommandRunner()
    profile = _profile(first_runner)
    request = _request(profile)
    path = tmp_path / "prepared.sqlite"
    original_compare_and_set = SQLiteReadyStageSubmissions._compare_and_set

    def crash_after_prepared(
        owner: SQLiteReadyStageSubmissions,
        operation_id: str,
        *,
        expected: ReadyStageState,
        value: SlurmReadyStageSubmission,
    ) -> SlurmReadyStageSubmission:
        result = original_compare_and_set(
            owner, operation_id, expected=expected, value=value
        )
        if value.capability is not None and value.state is ReadyStageState.INTENT:
            raise OSError("crash after durable prepared receipt")
        return result

    monkeypatch.setattr(
        SQLiteReadyStageSubmissions, "_compare_and_set", crash_after_prepared
    )
    with pytest.raises(OSError, match="durable prepared receipt"):
        SQLiteReadyStageSubmissions(path).submit(
            request, profile, _script(tmp_path, request)
        )

    class FailingProvider(SlurmJobPrivateFileProvider):
        def prepare(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("must not prepare")

    fresh_runner = FakeSlurmCommandRunner()
    reopened_profile = replace(
        profile,
        runner=fresh_runner,
        job_private_file_provider=FailingProvider(
            fixed_path="/tmp/loom-unit-capability",
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
    )
    result = SQLiteReadyStageSubmissions(path, _allow_initialize=False).submit(
        request, reopened_profile, _script(tmp_path, request)
    )
    assert result.state is ReadyStageState.ACCEPTED
    assert len([call for call in fresh_runner.calls if call[0] == "sbatch"]) == 1


def test_fresh_accepted_store_uses_neither_provider_nor_sbatch(tmp_path: Path) -> None:
    first_runner = FakeSlurmCommandRunner()
    profile = _profile(first_runner)
    request = _request(profile)
    path = tmp_path / "accepted.sqlite"
    assert (
        SQLiteReadyStageSubmissions(path)
        .submit(request, profile, _script(tmp_path, request))
        .state
        is ReadyStageState.ACCEPTED
    )

    class FailingProvider(SlurmJobPrivateFileProvider):
        def prepare(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("must not prepare")

    fresh_runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [AssertionError("must not submit")]}
    )
    reopened_profile = replace(
        profile,
        runner=fresh_runner,
        job_private_file_provider=FailingProvider(
            fixed_path="/tmp/loom-unit-capability",
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
    )
    assert (
        SQLiteReadyStageSubmissions(path, _allow_initialize=False)
        .submit(request, reopened_profile, _script(tmp_path, request))
        .state
        is ReadyStageState.ACCEPTED
    )
    assert not fresh_runner.calls


def test_fresh_unknown_store_reconciles_without_reprepare_or_resubmit(
    tmp_path: Path,
) -> None:
    first_runner = FakeSlurmCommandRunner(scripted_results={"sbatch": [TimeoutError()]})
    profile = _profile(first_runner)
    request = _request(profile)
    path = tmp_path / "unknown.sqlite"
    assert (
        SQLiteReadyStageSubmissions(path)
        .submit(request, profile, _script(tmp_path, request))
        .state
        is ReadyStageState.UNKNOWN
    )

    class FailingProvider(SlurmJobPrivateFileProvider):
        def prepare(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("must not prepare")

    marker = operation_marker(request.operation_id)
    fresh_runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [AssertionError("must not submit")],
            "squeue": [
                SlurmCommandResult("squeue", ("squeue",), 0, stdout=f"1200|{marker}\n")
            ],
            "sacct": [SlurmCommandResult("sacct", ("sacct",), 0)],
        }
    )
    reopened_profile = replace(
        profile,
        runner=fresh_runner,
        job_private_file_provider=FailingProvider(
            fixed_path="/tmp/loom-unit-capability",
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
    )
    result = SQLiteReadyStageSubmissions(path, _allow_initialize=False).reconcile(
        request.operation_id, reopened_profile
    )
    assert result.state is ReadyStageState.ACCEPTED
    assert result.job_id == "1200"
    assert not [call for call in fresh_runner.calls if call[0] == "sbatch"]


def test_ready_stage_rejects_a_managed_pool_requirement() -> None:
    profile = _profile(FakeSlurmCommandRunner())
    placement = resolve_stage_placement(
        authored=ResourceRequest(entries={"cpu": ResourceEntry("cpu", 2, "count")}),
        runtime=None,
        policy=StagePlacementPolicy(
            pool_name="managed-gpu-pool",
            route=ExecutionRoute(
                kind=ExecutionRouteKind.SLURM,
                profile_id=profile.profile_id,
                profile_descriptor=profile.descriptor,
                profile_configuration_fingerprint=profile.configuration_fingerprint,
            ),
        ),
        planners={"cpu": CpuResourcePlanner()},
    )

    with pytest.raises(SlurmResourceMappingError, match="unmappable"):
        map_ready_stage(
            placement=placement,
            profile=profile,
            operation_id="operation-pool",
            stage_work_id="work-pool",
            run_uri="runs/example",
            attempt_id="attempt-1",
        )


def test_submission_start_permit_is_atomic_across_bootstrap_incarnations(
    tmp_path: Path,
) -> None:
    """Only one concurrent bootstrap can receive the authored-root permit."""

    profile = _profile(FakeSlurmCommandRunner())
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    accepted = store.submit(request, profile, _script(tmp_path, request))
    assert accepted.state is ReadyStageState.ACCEPTED

    with ThreadPoolExecutor(max_workers=2) as executor:
        permits = list(
            executor.map(lambda _: store.consume_start("operation-1"), range(2))
        )

    assert permits.count(True) == 1
    assert permits.count(False) == 1
    assert store.read("operation-1").start_consumed is True


def test_unknown_submit_reconciles_only_one_exact_operation(tmp_path: Path) -> None:
    marker = operation_marker("operation-1")
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [TimeoutError("lost response")],
            "squeue": [
                SlurmCommandResult("squeue", ("squeue",), 0, stdout=f"1200|{marker}\n")
            ],
            "sacct": [SlurmCommandResult("sacct", ("sacct",), 0)],
        }
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    result = store.submit(request, profile, _script(tmp_path, request))

    assert result.state is ReadyStageState.UNKNOWN
    reconciled = store.reconcile(request.operation_id, profile)
    assert reconciled.state is ReadyStageState.ACCEPTED
    assert reconciled.job_id == "1200"
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
    assert store.submit(request, profile, _script(tmp_path, request)) == reconciled
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1


def test_zero_or_multiple_operation_matches_never_resubmit(tmp_path: Path) -> None:
    marker = operation_marker("operation-1")
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [TimeoutError("lost response")],
            "squeue": [
                SlurmCommandResult("squeue", ("squeue",), 0),
                SlurmCommandResult(
                    "squeue",
                    ("squeue",),
                    0,
                    stdout=f"1200|{marker}\n1201|{marker}\n",
                ),
            ],
            "sacct": [
                SlurmCommandResult("sacct", ("sacct",), 0),
                SlurmCommandResult("sacct", ("sacct",), 0),
            ],
        }
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    assert (
        store.reconcile(request.operation_id, profile).state is ReadyStageState.UNKNOWN
    )
    conflict = store.reconcile(request.operation_id, profile)
    assert conflict.state is ReadyStageState.CONFLICT
    assert set(conflict.conflicting_handles) == {
        ("1200", "cluster-a"),
        ("1201", "cluster-a"),
    }
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1


def test_live_and_accounting_views_of_one_job_reconcile_as_one_handle(
    tmp_path: Path,
) -> None:
    marker = operation_marker("operation-1")
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [TimeoutError("lost response")],
            "squeue": [
                SlurmCommandResult("squeue", ("squeue",), 0, stdout=f"1200|{marker}\n")
            ],
            "sacct": [
                SlurmCommandResult(
                    "sacct",
                    ("sacct",),
                    0,
                    stdout=f"1200|{marker}|cluster-a|\n",
                )
            ],
        }
    )
    profile = _profile(runner, cluster=None)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    reconciled = store.reconcile(request.operation_id, profile)

    assert reconciled.state is ReadyStageState.ACCEPTED
    assert reconciled.job_id == "1200"
    assert reconciled.cluster == "cluster-a"


def test_many_exact_matches_record_a_bounded_conflict(tmp_path: Path) -> None:
    marker = operation_marker("operation-1")
    rows = "".join(f"{job_id}|{marker}\n" for job_id in range(1200, 1220))
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [TimeoutError("lost response")],
            "squeue": [SlurmCommandResult("squeue", ("squeue",), 0, stdout=rows)],
            "sacct": [SlurmCommandResult("sacct", ("sacct",), 0)],
        }
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    conflict = store.reconcile(request.operation_id, profile)

    assert conflict.state is ReadyStageState.CONFLICT
    assert len(conflict.conflicting_handles) == 16


def test_bootstrap_handle_repairs_response_race_and_conflict_is_closed(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [TimeoutError("lost response")]}
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    accepted = store.associate_handle(
        request.operation_id, profile, job_id="1200", cluster="cluster-a"
    )
    assert accepted.state is ReadyStageState.ACCEPTED
    assert (
        store.associate_handle(
            request.operation_id, profile, job_id="1200", cluster="cluster-a"
        )
        == accepted
    )
    conflict = store.associate_handle(
        request.operation_id, profile, job_id="1201", cluster="cluster-a"
    )
    assert conflict.state is ReadyStageState.CONFLICT
    assert set(conflict.conflicting_handles) == {
        ("1200", "cluster-a"),
        ("1201", "cluster-a"),
    }


def test_bootstrap_handle_wins_a_late_unknown_submit_response(tmp_path: Path) -> None:
    entered = Event()
    release = Event()

    class BlockingRunner(FakeSlurmCommandRunner):
        def sbatch(
            self, script_path, *, dependency_job_ids=(), comment=None, environment=None
        ):  # type: ignore[no-untyped-def]
            del script_path, dependency_job_ids, comment, environment
            entered.set()
            assert release.wait(timeout=5)
            return SlurmCommandResult(
                "sbatch", ("sbatch",), 0, stdout="unusable-success"
            )

    runner = BlockingRunner()
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    script = _script(tmp_path, request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = executor.submit(store.submit, request, profile, script)
        assert entered.wait(timeout=5)
        associated = store.associate_handle(
            request.operation_id,
            profile,
            job_id="1200",
            cluster="cluster-a",
        )
        release.set()
        completed = pending.result(timeout=5)

    assert associated.state is ReadyStageState.ACCEPTED
    assert completed == associated
    assert store.read(request.operation_id) == associated


def test_two_concurrent_bootstrap_handles_close_as_conflict(tmp_path: Path) -> None:
    runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [TimeoutError("lost response")]}
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda job_id: store.associate_handle(
                    request.operation_id,
                    profile,
                    job_id=job_id,
                    cluster="cluster-a",
                ),
                ("1200", "1201"),
            )
        )

    assert ReadyStageState.CONFLICT in {result.state for result in results}
    conflict = store.read(request.operation_id)
    assert conflict.state is ReadyStageState.CONFLICT
    assert set(conflict.conflicting_handles) == {
        ("1200", "cluster-a"),
        ("1201", "cluster-a"),
    }


def test_changed_profile_and_script_bytes_are_rejected_before_sbatch(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    changed = _profile(runner, credential_reference="changed-credential")
    path = _script(tmp_path, request)

    with pytest.raises(SlurmPlanningError, match="profile identity"):
        SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite").submit(
            request, changed, path
        )
    path.write_text(request.script + "# changed\n", encoding="utf-8")
    with pytest.raises(SlurmPlanningError, match="script bytes"):
        SQLiteReadyStageSubmissions(tmp_path / "submissions-2.sqlite").submit(
            request, profile, path
        )
    assert not [call for call in runner.calls if call[0] == "sbatch"]


def test_unavailable_profile_rejects_the_exact_route_without_sbatch() -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, available=False)

    with pytest.raises(SlurmPlanningError, match="slurm_profile_unavailable"):
        _request(profile)

    assert not [call for call in runner.calls if call[0] == "sbatch"]


def test_exact_cancel_records_only_a_request_and_keeps_assignment_nonterminal(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    accepted = store.submit(request, profile, _script(tmp_path, request))

    cancelled = store.request_cancel(request.operation_id, profile)
    assert accepted.state is ReadyStageState.ACCEPTED
    assert cancelled.state is ReadyStageState.ACCEPTED
    assert cancelled.cancel_requested is True
    assert cancelled.job_id == accepted.job_id
    assert [call for call in runner.calls if call[0] == "scancel"] == [
        ("scancel", ("scancel", cast(str, accepted.job_id)))
    ]


def test_scheduler_completed_is_observation_not_loom_terminality(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "squeue": [
                SlurmCommandResult(
                    "squeue",
                    ("squeue",),
                    0,
                    stdout="1000|COMPLETED|None\n",
                )
            ]
        }
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    accepted = store.submit(request, profile, _script(tmp_path, request))

    observed = store.observe(request.operation_id, profile)

    assert accepted.state is ReadyStageState.ACCEPTED
    assert observed.state is ReadyStageState.ACCEPTED
    assert observed.scheduler_state == "COMPLETED"
    assert observed.scheduler_source == "squeue"
    assert observed.scheduler_observed_at is not None
    assert observed.start_consumed is False


def test_rejected_scancel_does_not_claim_cancellation_was_requested(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "scancel": [SlurmCommandResult("scancel", ("scancel", "1000"), 1)]
        }
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    result = store.request_cancel(request.operation_id, profile)

    assert result.state is ReadyStageState.ACCEPTED
    assert result.cancel_requested is False
    assert result.evidence == "slurm_cancel_request_rejected"
