"""Shared CLI text and JSON formatting helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast

from loom.cli.results import (
    CliWarning,
    PlanCliResult,
    PlainCliData,
    RunCliResult,
    SlurmDryRunCliResult,
    SlurmLiveRunCliResult,
    ValidationCliResult,
    to_plain_cli_data,
)

CLI_ERROR_SCHEMA_VERSION = "loom.cli.error.v2"
CLI_RESULT_SCHEMA_VERSION = "loom.cli.result.v2"


def _warning_to_dict(
    warning: Mapping[str, object] | CliWarning,
) -> dict[str, PlainCliData]:
    if isinstance(warning, CliWarning):
        return warning.to_dict()

    code = warning.get("code", "warning")
    message = warning.get("message", "")
    details = to_plain_cli_data(warning.get("details", {}))
    if not isinstance(details, dict):
        details = {}
    return {
        "code": str(code),
        "message": str(message),
        "details": details,
    }


def format_json_envelope(
    *,
    schema_version: str,
    ok: bool,
    warnings: Sequence[Mapping[str, object] | CliWarning],
    payload_name: str,
    payload: Mapping[str, object],
) -> str:
    """Format a stable JSON envelope with top-level warnings."""

    if payload_name not in {"result", "error"}:
        raise ValueError(f"Unsupported JSON envelope payload name: {payload_name!r}")

    envelope: dict[str, PlainCliData] = {
        "schema_version": schema_version,
        "ok": ok,
        "warnings": [_warning_to_dict(warning) for warning in warnings],
        payload_name: to_plain_cli_data(dict(payload)),
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n"


def format_validation_text(result: ValidationCliResult) -> str:
    """Format a concise validation result."""

    if result.stage_count is None:
        stage_summary = "unknown stages"
    elif result.stage_count == 1:
        stage_summary = "1 stage"
    else:
        stage_summary = f"{result.stage_count} stages"
    return f"OK validate {result.config_path}: {stage_summary}"


def format_plan_text(result: PlanCliResult) -> str:
    """Format a concise plan result."""

    action_count = len(result.stage_actions)
    suffix = "1 stage action" if action_count == 1 else f"{action_count} stage actions"
    lines: list[str]
    if result.run_uri is None:
        lines = [f"OK plan {result.config_path}: {suffix}"]
    else:
        lines = [f"OK plan {result.config_path}: {suffix}, run_uri={result.run_uri}"]

    for stage_action in result.stage_actions:
        stage_name = str(stage_action.get("stage", "<unknown>"))
        action = str(stage_action.get("action", "<unknown>"))
        reason_codes = stage_action.get("reason_codes", ())
        if isinstance(reason_codes, Sequence) and not isinstance(reason_codes, str):
            reasons = ", ".join(str(code) for code in reason_codes) or "NO_REASONS"
        else:
            reasons = str(reason_codes) if reason_codes else "NO_REASONS"
        lines.append(f"{stage_name}: {action} [{reasons}]")

    if result.explanation is not None:
        stage_name = str(result.explanation.get("stage", "<unknown>"))
        lines.append(f"explain {stage_name}:")
        explanation_reasons = result.explanation.get("reasons", ())
        if not isinstance(explanation_reasons, Sequence) or isinstance(
            explanation_reasons, str
        ):
            explanation_reasons = ()
        for reason in explanation_reasons:
            if not isinstance(reason, Mapping):
                continue
            code = str(reason.get("code", "reason"))
            message = str(reason.get("message", ""))
            lines.append(f"  {code}: {message}")

    return "\n".join(lines)


def format_preflight_text(result: object, *, config_path: object) -> str:
    """Format a concise preflight result."""

    status = _enum_value(getattr(result, "status"))
    prefix = {
        "PASS": "OK",
        "WARN": "WARN",
        "FAIL": "FAILED",
        "SKIP": "SKIP",
    }.get(status, status)
    lines = [f"{prefix} preflight {config_path}: {status}"]
    for check in getattr(result, "checks", ()):
        check_status = _enum_value(getattr(check, "status"))
        check_id = str(getattr(check, "check_id"))
        message = str(getattr(check, "message"))
        lines.append(f"{check_status} {check_id}: {message}")
        details = getattr(check, "details", {})
        if isinstance(details, Mapping):
            source = details.get("state_source")
            if isinstance(source, Mapping):
                lines.append(f"  source: {source.get('label', 'unknown')}")
            guidance = details.get("guidance")
            if isinstance(guidance, str) and guidance:
                lines.append(f"  guidance: {guidance}")
    return "\n".join(lines)


def format_queue_preflight_text(result: object) -> str:
    """Format queue preflight output."""

    status = _enum_value(getattr(result, "status"))
    prefix = {
        "PASS": "OK",
        "WARN": "WARN",
        "FAIL": "FAILED",
        "SKIP": "SKIP",
    }.get(status, status)
    lines = [f"{prefix} queue preflight {getattr(result, 'config_path')}: {status}"]
    for check in getattr(result, "checks", ()):
        check_status = _enum_value(getattr(check, "status"))
        check_id = str(getattr(check, "check_id"))
        message = str(getattr(check, "message"))
        lines.append(f"{check_status} {check_id}: {message}")
        details = getattr(check, "details", {})
        if isinstance(details, Mapping):
            missing = details.get("missing")
            if (
                isinstance(missing, Sequence)
                and not isinstance(missing, str)
                and missing
            ):
                lines.append("  missing: " + ", ".join(str(item) for item in missing))
            reason = details.get("reason")
            if isinstance(reason, str) and reason:
                lines.append(f"  reason: {reason}")
    return "\n".join(lines)


def format_run_text(result: RunCliResult) -> str:
    """Format a concise run result."""

    prefix = "OK" if result.status == "SUCCEEDED" else "FAILED"
    lines = [f"{prefix} run {result.run_uri}: {result.status}"]
    for stage in result.stage_summaries:
        stage_name = str(stage.get("stage", "<unknown>"))
        action = str(stage.get("action", "<unknown>"))
        status = str(stage.get("status", "<none>"))
        lines.append(f"{stage_name}: {action} -> {status}")
    if result.failure_summary is not None:
        stage_name = result.failure_summary.get("stage", "<unknown>")
        message = result.failure_summary.get("message", "")
        lines.append(f"failure {stage_name}: {message}")
        for label, key in (
            ("attempt", "attempt"),
            ("executor", "executor"),
            ("exit_code", "exit_code"),
            ("signal", "signal"),
            ("failure_record", "failure_path"),
            ("stdout", "stdout_path"),
            ("stderr", "stderr_path"),
            ("traceback", "traceback_path"),
        ):
            value = result.failure_summary.get(key)
            if value is not None:
                lines.append(f"  {label}: {value}")
    if result.offline_evidence is not None:
        manifest_path = result.offline_evidence.get("manifest_path")
        manifest_status = result.offline_evidence.get("manifest_status")
        lines.append(f"offline_evidence: {manifest_status} {manifest_path}")
    return "\n".join(lines)


def format_slurm_dry_run_text(result: SlurmDryRunCliResult) -> str:
    """Format a concise SLURM dry-run artifact summary."""

    suffix = (
        "1 script" if result.script_count == 1 else f"{result.script_count} scripts"
    )
    lines = [
        f"OK slurm dry-run {result.run_uri}: {result.mode}",
        f"planning_id: {result.planning_id}",
        f"manifest: {result.manifest_path}",
        f"plan: {result.plan_path}",
        f"scripts: {suffix}"
        + ("" if result.script_directory is None else f" in {result.script_directory}"),
        f"logs: {_slurm_log_summary(result.log_paths)}",
        f"jobs: {result.job_count}",
        f"dependencies: {result.dependency_count}",
    ]
    if result.preflight_warnings:
        warning_suffix = (
            "1 warning"
            if len(result.preflight_warnings) == 1
            else f"{len(result.preflight_warnings)} warnings"
        )
        lines.append(f"warnings: {warning_suffix}")
        for warning in result.preflight_warnings:
            code = str(warning.get("code", "warning"))
            message = str(warning.get("message", ""))
            lines.append(f"  {code}: {message}")
    return "\n".join(lines)


def format_slurm_live_submission_text(result: SlurmLiveRunCliResult) -> str:
    """Format a concise SLURM live submission summary."""

    suffix = (
        "1 submitted job"
        if result.submitted_job_count == 1
        else f"{result.submitted_job_count} submitted jobs"
    )
    prefix = "OK" if result.status == "SUBMITTED" else "PARTIAL"
    lines = [
        f"{prefix} slurm submit {result.run_uri}: {result.mode} {result.status}",
        f"submission_id: {result.submission_id}",
        f"manifest: {result.manifest_path}",
        f"plan: {result.plan_path}",
        f"jobs: {suffix} of {result.job_count}",
    ]
    for job in result.submitted_jobs:
        cluster = job.get("scheduler_cluster")
        cluster_suffix = "" if cluster is None else f";{cluster}"
        lines.append(
            f"  {job.get('logical_key')}: {job.get('scheduler_job_id')}{cluster_suffix}"
        )
    for failed in result.failed_submissions:
        lines.append(f"  failed {failed.get('logical_key')}: {failed.get('reason')}")
    if result.log_paths:
        lines.append(f"logs: {_slurm_log_summary(result.log_paths)}")
    if result.status == "PARTIAL":
        lines.append(f"failed: {result.failed_submission_count}")
        lines.append(
            "cancel: loom cancel {run_uri} --jobs".format(run_uri=result.run_uri)
        )
    lines.append(f"status: loom status {result.run_uri} --jobs")
    return "\n".join(lines)


def _slurm_log_summary(log_paths: Sequence[Mapping[str, object]]) -> str:
    if not log_paths:
        return "none"
    first = log_paths[0]
    stdout = str(first.get("stdout_relative_path", ""))
    stderr = str(first.get("stderr_relative_path", ""))
    if len(log_paths) == 1:
        return f"stdout={stdout}, stderr={stderr}"
    parent = stdout.rsplit("/", 1)[0] if "/" in stdout else stdout
    return f"{len(log_paths)} job log pairs under {parent}"


def format_stage_worker_text(result: object) -> str:
    """Format one direct worker result."""

    status = _enum_value(getattr(result, "status"))
    prefix = (
        "OK"
        if status == "SUCCEEDED"
        else "CANCELLED"
        if status == "CANCELLED"
        else "FAILED"
    )
    run_uri = str(getattr(result, "run_uri"))
    stage_name = str(getattr(result, "stage_name"))
    attempt = int(getattr(result, "attempt"))
    lines = [f"{prefix} stage run {run_uri} {stage_name} attempt {attempt}: {status}"]
    failure = getattr(result, "failure")
    if failure is not None:
        message = str(getattr(failure, "message", ""))
        failure_type = str(getattr(failure, "failure_type", "failure"))
        lines.append(f"failure {failure_type}: {message}")
    return "\n".join(lines)


def format_stage_job_text(result: object) -> str:
    """Format one self-finalizing stage-job result."""

    status = _enum_value(getattr(result, "status"))
    run_status = _enum_value(getattr(result, "run_status"))
    prefix = "OK" if status == "SUCCEEDED" else "FAILED"
    run_uri = str(getattr(result, "run_uri"))
    stage_name = str(getattr(result, "stage_name"))
    attempt = int(getattr(result, "attempt"))
    lines = [
        f"{prefix} stage-job run {run_uri} {stage_name} attempt {attempt}: {status}",
        f"run: {run_status}",
    ]
    failure = getattr(result, "failure")
    if failure is not None:
        message = str(getattr(failure, "message", ""))
        failure_type = str(getattr(failure, "failure_type", "failure"))
        lines.append(f"failure {failure_type}: {message}")
    return "\n".join(lines)


def format_prepared_run_continue_text(error: object) -> str:
    """Format a prepared-run continuation failure."""

    return f"FAILED prepared-run continue: {error}"


def format_status_text(result: object) -> str:
    """Format a concise run status summary."""

    run_uri = str(getattr(result, "run_uri"))
    status = getattr(result, "status")
    status_text = "<unknown>" if status is None else str(status)
    lines = [f"status {run_uri}: {status_text}"]
    source = getattr(result, "state_source", {})
    if isinstance(source, Mapping):
        lines.append(f"source: {source.get('label', 'unknown')}")
    import_provenance = getattr(result, "import_provenance", None)
    if isinstance(import_provenance, Mapping):
        imported_at = import_provenance.get("imported_at", "<unknown>")
        manifest_generated_at = import_provenance.get(
            "manifest_generated_at", "<unknown>"
        )
        lines.append(
            "imported_from: offline_evidence "
            f"imported_at={imported_at} manifest_generated_at={manifest_generated_at}"
        )
    submitted_operations = cast(
        Sequence[object], getattr(result, "submitted_operations", ())
    )
    if submitted_operations:
        lines.append("submitted operations:")
        for operation in submitted_operations:
            active_suffix = " active" if bool(getattr(operation, "active")) else ""
            lines.append(
                "  "
                f"{getattr(operation, 'submission_id')}: "
                f"{getattr(operation, 'backend')}/{getattr(operation, 'mode')} "
                f"{getattr(operation, 'state')}{active_suffix} "
                f"manifest={getattr(operation, 'manifest_relative_path')}"
            )
    for stage in getattr(result, "stages", ()):
        stage_name = str(getattr(stage, "stage_name"))
        stage_status = getattr(stage, "status")
        stage_status_text = "<missing>" if stage_status is None else str(stage_status)
        output_count = int(getattr(stage, "output_count"))
        suffix = (
            f"{output_count} output" if output_count == 1 else f"{output_count} outputs"
        )
        lines.append(f"{stage_name}: {stage_status_text} ({suffix})")
        stage_source = getattr(stage, "state_source", {})
        if isinstance(stage_source, Mapping):
            lines.append(f"  source: {stage_source.get('label', 'unknown')}")
        reliability = getattr(stage, "reliability", None)
        if reliability is not None:
            lines.extend(_format_stage_reliability_text(reliability))
        failure = getattr(stage, "failure")
        if isinstance(failure, Mapping):
            message = failure.get("message")
            if message:
                lines.append(f"  failure: {message}")
    lines.append(f"artifacts: {getattr(result, 'artifact_count')}")
    return "\n".join(lines)


def _format_stage_reliability_text(reliability: object) -> list[str]:
    lines: list[str] = []
    counts = _stage_reliability_counts(reliability)
    if any(counts.values()):
        lines.append(
            "  reliability: "
            f"policies={counts['policy_facts']} "
            f"status_details={counts['status_details']} "
            f"transactions={counts['transactions']} "
            f"retries={counts['retry_decisions']} "
            f"timeouts={counts['timeout_outcomes']} "
            f"unsupported_timeouts={counts['unsupported_timeouts']}"
        )
    latest_policy = getattr(reliability, "latest_policy", None)
    if isinstance(latest_policy, Mapping):
        policy_text = _reliability_policy_text(latest_policy)
        if policy_text:
            lines.append(f"  policy: {policy_text}")
    latest_transaction = getattr(reliability, "latest_transaction", None)
    if isinstance(latest_transaction, Mapping):
        state = latest_transaction.get("state")
        attempt = latest_transaction.get("attempt")
        if state is not None:
            lines.append(f"  transaction: {state} attempt={attempt}")
    latest_retry = getattr(reliability, "latest_retry_decision", None)
    if isinstance(latest_retry, Mapping):
        reason = latest_retry.get("decision_reason")
        should_retry = latest_retry.get("should_retry")
        if reason is not None:
            lines.append(f"  retry: {reason} retry={should_retry}")
    latest_timeout = getattr(reliability, "latest_timeout_outcome", None)
    if isinstance(latest_timeout, Mapping):
        outcome = latest_timeout.get("outcome")
        support = latest_timeout.get("support_level")
        if outcome is not None:
            lines.append(f"  timeout: {outcome} support={support}")
    for diagnostic in getattr(reliability, "diagnostics", ()):
        if isinstance(diagnostic, Mapping):
            lines.append(
                f"  diagnostic: {diagnostic.get('code')}: {diagnostic.get('message')}"
            )
    return lines


def _stage_reliability_counts(reliability: object) -> dict[str, int]:
    return {
        "policy_facts": int(getattr(reliability, "policy_count", 0)),
        "status_details": int(getattr(reliability, "status_detail_count", 0)),
        "transactions": int(getattr(reliability, "transaction_count", 0)),
        "retry_decisions": int(getattr(reliability, "retry_decision_count", 0)),
        "timeout_outcomes": int(getattr(reliability, "timeout_outcome_count", 0)),
        "unsupported_timeouts": int(
            getattr(reliability, "unsupported_timeout_count", 0)
        ),
    }


def _reliability_policy_text(policy_fact: Mapping[str, object]) -> str:
    policy = policy_fact.get("policy")
    if not isinstance(policy, Mapping):
        return ""
    parts: list[str] = []
    retry = policy.get("retry")
    if isinstance(retry, Mapping):
        enabled = "enabled" if retry.get("enabled") is True else "disabled"
        parts.append(f"retry={enabled} max_attempts={retry.get('max_attempts')}")
    else:
        parts.append("retry=unset")
    timeout = policy.get("timeout")
    if isinstance(timeout, Mapping):
        enabled = "enabled" if timeout.get("enabled") is True else "disabled"
        parts.append(
            f"timeout={enabled} duration_seconds={timeout.get('duration_seconds')}"
        )
    else:
        parts.append("timeout=unset")
    return " ".join(parts)


def format_status_jobs_text(result: object) -> str:
    """Format scheduler-aware submitted job status."""

    run_uri = str(getattr(result, "run_uri"))
    run_status = getattr(result, "run_status")
    status_text = "<unknown>" if run_status is None else str(run_status)
    lines = [f"status {run_uri} jobs: {status_text}"]
    submission = getattr(result, "submission")
    if isinstance(submission, Mapping):
        lines.append(
            "submission: "
            f"{submission.get('submission_id')} "
            f"{submission.get('backend')}/{submission.get('mode')} "
            f"{submission.get('state')} "
            f"manifest={submission.get('manifest_relative_path')}"
        )
    for job in getattr(result, "jobs", ()):
        logical_key = str(getattr(job, "logical_key"))
        scheduler_job_id = str(getattr(job, "scheduler_job_id"))
        status = str(getattr(job, "status"))
        source = str(getattr(job, "source"))
        scheduler_state = str(getattr(job, "scheduler_state"))
        exit_code = getattr(job, "exit_code")
        suffix = "" if exit_code is None else f" exit={exit_code}"
        lines.append(
            f"{logical_key}: {scheduler_job_id} {status} "
            f"scheduler={scheduler_state} source={source}{suffix}"
        )
        dependency_state = getattr(job, "dependency_state")
        if dependency_state is not None:
            dependencies = ", ".join(
                str(item) for item in getattr(job, "dependency_job_ids", ())
            )
            lines.append(f"  dependency: {dependency_state} [{dependencies}]")
        log_paths = getattr(job, "log_paths")
        if isinstance(log_paths, Mapping) and log_paths:
            stdout = log_paths.get("stdout_relative_path")
            stderr = log_paths.get("stderr_relative_path")
            lines.append(f"  logs: stdout={stdout}, stderr={stderr}")
        for warning in getattr(job, "warnings", ()):
            lines.append(
                f"  warning {getattr(warning, 'code')}: {getattr(warning, 'message')}"
            )
    failed = cast(
        Sequence[Mapping[str, object]], getattr(result, "failed_submissions", ())
    )
    for item in failed:
        lines.append(f"failed {item.get('logical_key')}: {item.get('reason')}")
    warnings = getattr(result, "warnings", ())
    if warnings:
        lines.append("warnings:")
        for warning in warnings:
            lines.append(f"  {getattr(warning, 'code')}: {getattr(warning, 'message')}")
    return "\n".join(lines)


def format_queue_status_text(result: object) -> str:
    """Format queue service and item status output."""

    service = getattr(result, "service_status")
    state = _enum_value(getattr(service, "state"))
    pools = ", ".join(str(name) for name in getattr(service, "pool_names"))
    queues = ", ".join(str(name) for name in getattr(service, "queue_names"))
    recovery = tuple(getattr(service, "recovery_records", ()))
    lines = [
        f"queue service: {state}",
        f"scope: {getattr(result, 'service_scope', 'in_process_command')}",
        f"pools: {pools or '<none>'}",
        f"queues: {queues or '<none>'}",
        f"recovery: {len(recovery)} active item(s)",
    ]
    inspection = getattr(result, "item_inspection", None)
    if inspection is not None:
        item = getattr(inspection, "item")
        if item is None:
            lines.append("item: <missing>")
        else:
            lines.extend(_queue_item_lines(item))
            audit_events = tuple(getattr(inspection, "audit_events", ()))
            lines.append(f"audit_events: {len(audit_events)}")
    active_items = cast(Sequence[object], getattr(result, "active_items", ()))
    if active_items:
        lines.append("active inspections:")
        for active in active_items:
            item = getattr(active, "item")
            lines.append(
                f"  {getattr(item, 'queue_item_id')}: {_enum_value(getattr(active, 'status'))}"
            )
            adapter_inspection = getattr(active, "adapter_inspection")
            if adapter_inspection is not None:
                lines.append(f"    adapter: {getattr(adapter_inspection, 'reason')}")
    lines.extend(_queue_ownership_lines(getattr(result, "to_dict")()))
    return "\n".join(lines)


def format_queue_cancel_text(result: object) -> str:
    """Format queue cancellation output."""

    item = getattr(result, "item")
    status = _enum_value(getattr(item, "status"))
    lines = [f"queue cancel {getattr(item, 'queue_item_id')}: {status}"]
    cancellation = getattr(item, "cancellation")
    if cancellation is not None:
        lines.append(f"reason: {getattr(cancellation, 'reason')}")
        evidence = getattr(cancellation, "evidence", {})
        if isinstance(evidence, Mapping) and evidence:
            outcome = evidence.get("cancellation_outcome")
            if outcome is not None:
                lines.append(f"adapter_outcome: {outcome}")
    lines.extend(_queue_ownership_lines(getattr(result, "to_dict")()))
    return "\n".join(lines)


def format_queue_drain_text(result: object) -> str:
    """Format foreground queue drain output."""

    steps = tuple(getattr(result, "steps", ()))
    recovery_records = tuple(getattr(result, "recovery_records", ()))
    lines = [f"queue drain foreground: {len(steps)} step(s)"]
    for step in steps:
        item = getattr(step, "item")
        item_id = "<none>" if item is None else str(getattr(item, "queue_item_id"))
        status = "" if item is None else f" {_enum_value(getattr(item, 'status'))}"
        lines.append(f"{getattr(step, 'outcome')}: {item_id}{status}")
    lines.append(f"recovery: {len(recovery_records)} active item(s)")
    return "\n".join(lines)


def format_cancel_jobs_text(result: object) -> str:
    """Format submitted-job cancellation output."""

    run_uri = str(getattr(result, "run_uri"))
    status = str(getattr(result, "status"))
    prefix = "OK" if bool(getattr(result, "ok")) else "PARTIAL"
    lines = [
        f"{prefix} cancel {run_uri}: {status}",
        f"submission_id: {getattr(result, 'submission_id')}",
        f"manifest: {getattr(result, 'manifest_path')}",
        (
            "jobs: "
            f"{getattr(result, 'cancelled_count')} cancelled, "
            f"{getattr(result, 'failed_count')} failed, "
            f"{getattr(result, 'skipped_count')} skipped, "
            f"{getattr(result, 'unknown_count')} unknown"
        ),
    ]
    run_status_before = getattr(result, "run_status_before")
    run_status_after = getattr(result, "run_status_after")
    if run_status_before != run_status_after:
        lines.append(f"run: {run_status_before} -> {run_status_after}")
    for job in getattr(result, "job_results", ()):
        outcome = str(getattr(job, "outcome"))
        scheduler_job_id = str(getattr(job, "scheduler_job_id"))
        logical_key = str(getattr(job, "logical_key"))
        message = getattr(job, "message")
        suffix = "" if message is None else f" ({message})"
        lines.append(f"{logical_key}: {scheduler_job_id} {outcome}{suffix}")
    return "\n".join(lines)


def format_logs_text(result: object) -> str:
    """Format bounded stage log content."""

    run_uri = str(getattr(result, "run_uri"))
    stage_name = str(getattr(result, "stage_name"))
    lines = [f"logs {run_uri} {stage_name}:"]
    for stream in getattr(result, "streams", ()):
        stream_name = str(getattr(stream, "stream"))
        path = str(getattr(stream, "path"))
        available = bool(getattr(stream, "available"))
        lines.append(f"{stream_name}: {path}")
        content = getattr(stream, "content", None)
        if content is not None:
            lines.append(str(content).rstrip("\n"))
        elif not available:
            lines.append("  <missing>")
    return "\n".join(lines)


def format_artifacts_list_text(result: object) -> str:
    """Format artifact metadata summaries."""

    run_uri = str(getattr(result, "run_uri"))
    artifact_count = int(getattr(result, "artifact_count"))
    suffix = "1 artifact" if artifact_count == 1 else f"{artifact_count} artifacts"
    lines = [f"artifacts {run_uri}: {suffix}"]
    for artifact in getattr(result, "artifacts", ()):
        key = str(getattr(artifact, "key"))
        artifact_id = str(getattr(artifact, "artifact_id"))
        artifact_type = str(getattr(artifact, "artifact_type"))
        uri = str(getattr(artifact, "uri"))
        lines.append(f"{key}: {artifact_id} ({artifact_type}) {uri}")
    return "\n".join(lines)


def format_artifact_show_text(result: object) -> str:
    """Format one artifact metadata summary."""

    artifact = getattr(result, "artifact")
    key = str(getattr(artifact, "key"))
    artifact_id = str(getattr(artifact, "artifact_id"))
    lines = [f"artifact {artifact_id} ({key})"]
    lines.append(f"uri: {getattr(artifact, 'uri')}")
    lines.append(f"type: {getattr(artifact, 'artifact_type')}")
    codec_key = getattr(artifact, "codec_key")
    if codec_key is not None:
        lines.append(f"codec: {codec_key}")
    checksum = getattr(artifact, "checksum")
    if checksum is not None:
        lines.append(f"checksum: {checksum}")
    producer_stage = getattr(artifact, "producer_stage")
    if producer_stage is not None:
        lines.append(f"producer: {producer_stage}")
    metadata = getattr(artifact, "metadata")
    if isinstance(metadata, Mapping) and metadata:
        keys = ", ".join(sorted(str(key) for key in metadata))
        lines.append(f"metadata: {keys}")
    provenance = getattr(result, "stage_provenance")
    if isinstance(provenance, Mapping) and provenance:
        keys = ", ".join(sorted(str(key) for key in provenance))
        lines.append(f"stage_provenance: {keys}")
    elif provenance is None:
        lines.append("stage_provenance: <missing>")
    return "\n".join(lines)


def format_runs_index_text(
    result: object,
    *,
    collection_path: object,
    warnings: Sequence[Mapping[str, object] | CliWarning] = (),
) -> str:
    """Format run-catalog index output."""

    indexed_count = int(getattr(result, "indexed_count"))
    skipped_count = int(getattr(result, "skipped_count"))
    lines = [
        f"runs index {collection_path}: {indexed_count} indexed, {skipped_count} skipped"
    ]
    checked_at = getattr(result, "checked_at")
    if checked_at is not None:
        lines.append(f"checked_at: {checked_at}")
    _extend_warning_lines(lines, warnings)
    return "\n".join(lines)


def format_runs_list_text(
    result: object,
    *,
    collection_path: object,
    warnings: Sequence[Mapping[str, object] | CliWarning] = (),
) -> str:
    """Format run-catalog list output."""

    summaries = tuple(getattr(result, "summaries"))
    suffix = "1 run" if len(summaries) == 1 else f"{len(summaries)} runs"
    lines = [f"runs list {collection_path}: {suffix}"]
    for summary in summaries:
        run_uri = str(getattr(summary, "run_uri"))
        status = getattr(summary, "status")
        status_text = "<unknown>" if status is None else str(status)
        parts = [status_text, run_uri]
        config = getattr(summary, "config_fingerprint")
        pipeline = getattr(summary, "pipeline_fingerprint")
        commit = getattr(summary, "git_commit")
        if config is not None:
            parts.append(f"config={config}")
        if pipeline is not None:
            parts.append(f"pipeline={pipeline}")
        if commit is not None:
            parts.append(f"commit={commit}")
        parts.append(f"stages={len(getattr(summary, 'stages'))}")
        parts.append(f"artifacts={len(getattr(summary, 'artifacts'))}")
        source = getattr(summary, "state_source", {})
        if isinstance(source, Mapping):
            parts.append(f"source={source.get('label', 'unknown')}")
        lines.append(" ".join(parts))
    _extend_warning_lines(lines, warnings)
    return "\n".join(lines)


def format_runs_diff_text(
    result: object,
    *,
    warnings: Sequence[Mapping[str, object] | CliWarning] = (),
) -> str:
    """Format run-catalog diff output."""

    left_run_uri = str(getattr(result, "left_run_uri"))
    right_run_uri = str(getattr(result, "right_run_uri"))
    entries = [
        entry
        for section in getattr(result, "sections")
        for entry in getattr(section, "entries")
    ]
    status_counts: dict[str, int] = {}
    for entry in entries:
        status = _enum_value(getattr(entry, "status"))
        status_counts[status] = status_counts.get(status, 0) + 1
    lines = [
        f"runs diff {left_run_uri} {right_run_uri}: "
        f"{_comparison_status_summary(status_counts)}"
    ]
    for entry in entries:
        status = _enum_value(getattr(entry, "status"))
        if status == "same":
            continue
        left = _text_value(getattr(entry, "left"))
        right = _text_value(getattr(entry, "right"))
        lines.append(f"{getattr(entry, 'key')}: {status} left={left} right={right}")
    _extend_warning_lines(lines, warnings)
    return "\n".join(lines)


def format_runs_export_text(result: object, *, destination_path: object) -> str:
    """Format run bundle export output."""

    status = _enum_value(getattr(result, "status"))
    manifest = getattr(result, "manifest", None)
    run_uri = "<unknown>" if manifest is None else str(getattr(manifest, "run_uri"))
    lines = [
        f"runs export {run_uri}: {status} destination={destination_path} "
        f"payloads={getattr(result, 'exported_payload_count')}"
    ]
    if manifest is not None:
        lines.append(
            f"bundle: entries={len(getattr(manifest, 'entries'))} "
            f"payload_refs={len(getattr(manifest, 'payload_refs'))}"
        )
        _extend_identity_lines(lines, manifest)
    _extend_exchange_diagnostic_lines(lines, getattr(result, "diagnostics", ()))
    return "\n".join(lines)


def format_runs_inspect_text(result: object, *, bundle_path: object) -> str:
    """Format run bundle inspection output."""

    status = _enum_value(getattr(result, "status"))
    manifest = getattr(result, "manifest")
    lines = [
        f"runs inspect {bundle_path}: {status} run_uri={getattr(manifest, 'run_uri')} "
        f"payloads={getattr(result, 'included_payload_count')}"
    ]
    lines.append(
        f"bundle: schema={getattr(manifest, 'schema_version')} "
        f"format={getattr(manifest, 'format_version')} "
        f"entries={len(getattr(manifest, 'entries'))} "
        f"payload_refs={len(getattr(manifest, 'payload_refs'))}"
    )
    _extend_identity_lines(lines, manifest)
    _extend_exchange_diagnostic_lines(lines, getattr(result, "diagnostics", ()))
    return "\n".join(lines)


def format_runs_import_text(
    result: object,
    *,
    bundle_path: object,
    target_collection: object,
) -> str:
    """Format run bundle import output."""

    status = _enum_value(getattr(result, "status"))
    target_run_uri = getattr(result, "target_run_uri")
    lines = [
        f"runs import {bundle_path}: {status} target={target_run_uri or '<none>'} "
        f"entries={getattr(result, 'imported_entry_count')} "
        f"payloads={getattr(result, 'imported_payload_count')}"
    ]
    lines.append(f"target_collection: {target_collection}")
    source = getattr(result, "source_identity")
    lines.append(
        f"source: kind={_enum_value(getattr(source, 'source_kind'))} "
        f"run_uri={getattr(source, 'run_uri')}"
    )
    readiness = getattr(result, "readiness")
    blockers = tuple(getattr(readiness, "blockers"))
    lines.append(
        f"readiness: mode={_enum_value(getattr(readiness, 'mode'))} "
        f"blockers={len(blockers)}"
    )
    for blocker in blockers:
        lines.append(
            f"  {_enum_value(getattr(blocker, 'code'))}: {getattr(blocker, 'message')}"
        )
    _extend_exchange_diagnostic_lines(lines, getattr(result, "diagnostics", ()))
    return "\n".join(lines)


def _comparison_status_summary(status_counts: Mapping[str, int]) -> str:
    ordered = [
        ("different", status_counts.get("different", 0)),
        ("left_only", status_counts.get("left_only", 0)),
        ("right_only", status_counts.get("right_only", 0)),
        ("unknown", status_counts.get("unknown", 0)),
        ("same", status_counts.get("same", 0)),
    ]
    return ", ".join(f"{key}={value}" for key, value in ordered if value)


def _extend_warning_lines(
    lines: list[str],
    warnings: Sequence[Mapping[str, object] | CliWarning],
) -> None:
    if not warnings:
        return
    suffix = "1 warning" if len(warnings) == 1 else f"{len(warnings)} warnings"
    lines.append(f"warnings: {suffix}")
    for warning in warnings:
        if isinstance(warning, CliWarning):
            code = warning.code
            message = warning.message
        else:
            code = str(warning.get("code", "warning"))
            message = str(warning.get("message", ""))
        lines.append(f"  {code}: {message}")


def _extend_exchange_diagnostic_lines(lines: list[str], diagnostics: object) -> None:
    if not isinstance(diagnostics, Sequence) or isinstance(diagnostics, str):
        return
    items = tuple(diagnostics)
    if not items:
        return
    suffix = "1 diagnostic" if len(items) == 1 else f"{len(items)} diagnostics"
    lines.append(f"diagnostics: {suffix}")
    for diagnostic in items:
        severity = _enum_value(getattr(diagnostic, "severity", "error"))
        code = getattr(diagnostic, "code", "diagnostic")
        message = getattr(diagnostic, "message", "")
        lines.append(f"  {severity} {code}: {message}")


def _extend_identity_lines(lines: list[str], manifest: object) -> None:
    source = getattr(manifest, "source_identity")
    lines.append(
        f"source: kind={_enum_value(getattr(source, 'source_kind'))} "
        f"run_uri={getattr(source, 'run_uri')}"
    )
    target = getattr(manifest, "target_identity")
    lines.append(f"target_identity: mode={_enum_value(getattr(target, 'mode'))}")


def _text_value(value: object) -> str:
    if value is None:
        return "<unknown>"
    if isinstance(value, Mapping):
        return "{" + ",".join(sorted(str(key) for key in value)) + "}"
    if isinstance(value, list | tuple):
        return "[" + ",".join(str(item) for item in value) + "]"
    return str(value)


def _enum_value(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value)


def _queue_item_lines(item: object) -> list[str]:
    lines = [
        f"item {getattr(item, 'queue_item_id')}: {_enum_value(getattr(item, 'status'))}",
        f"run_uri: {getattr(item, 'run_uri')}",
        f"queue: {getattr(item, 'queue_name')} pool={getattr(item, 'pool_name')}",
        f"adapter: {getattr(getattr(item, 'launch_contract'), 'adapter')}",
        f"dispatch_attempt: {getattr(item, 'dispatch_attempt')}",
    ]
    handle = getattr(item, "dispatch_handle")
    if handle is not None:
        lines.append(
            f"handle: {getattr(handle, 'adapter')} {getattr(handle, 'handle_id')}"
        )
        evidence = getattr(handle, "evidence", {})
        if isinstance(evidence, Mapping):
            handoff = evidence.get("delegated_handoff")
            if isinstance(handoff, Mapping):
                lines.append(
                    "delegated_handoff: "
                    f"durable={handoff.get('durable')} "
                    f"status_read={handoff.get('downstream_status_read_succeeded')}"
                )
            verification = evidence.get("delegated_launch_verification")
            if isinstance(verification, Mapping):
                summary = verification.get("summary")
                if isinstance(summary, Mapping):
                    lines.append(
                        "delegated_verification: "
                        f"proven={summary.get('proven_count')} "
                        f"unproven={summary.get('unproven_count')}"
                    )
    cancellation = getattr(item, "cancellation")
    if cancellation is not None:
        lines.append(f"cancellation: {getattr(cancellation, 'reason')}")
    return lines


def _queue_ownership_lines(payload: object) -> list[str]:
    if not isinstance(payload, Mapping):
        return []
    ownership = payload.get("ownership")
    if not isinstance(ownership, Mapping):
        return []
    return [
        "ownership:",
        f"  queue: {ownership.get('queue_state')}",
        f"  authority: {ownership.get('authority_state')}",
        f"  delegated: {ownership.get('delegated_scheduler_state')}",
    ]


__all__ = [
    "CLI_ERROR_SCHEMA_VERSION",
    "CLI_RESULT_SCHEMA_VERSION",
    "format_artifact_show_text",
    "format_artifacts_list_text",
    "format_cancel_jobs_text",
    "format_json_envelope",
    "format_plan_text",
    "format_preflight_text",
    "format_queue_cancel_text",
    "format_queue_drain_text",
    "format_queue_preflight_text",
    "format_queue_status_text",
    "format_runs_diff_text",
    "format_runs_export_text",
    "format_runs_import_text",
    "format_runs_index_text",
    "format_runs_inspect_text",
    "format_runs_list_text",
    "format_slurm_live_submission_text",
    "format_slurm_dry_run_text",
    "format_stage_worker_text",
    "format_logs_text",
    "format_run_text",
    "format_status_jobs_text",
    "format_status_text",
    "format_validation_text",
]
