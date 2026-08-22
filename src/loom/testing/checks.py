"""Bounded, caller-sampled checks for public extension contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, cast

from loom.io.codecs.base import Codec
from loom.pipeline.executors.base import Executor
from loom.pipeline.resources import (
    ResourceEntry,
    ResourceValidator,
    ResourceValidatorRegistry,
    validate_resource_kind,
)
from loom.scheduling import (
    HardConstraintResult,
    PolicyDecision,
    PolicyContext,
    PreferenceResult,
    ResourceAvailabilityEnvelope,
    ResourceInventoryEnvelope,
    ValidatedResourceEntryView,
    WorkItem,
)

from .reports import ContractFinding, ContractReport


def check_resource_planner_contract(
    planner: object,
    *,
    authored: ValidatedResourceEntryView | None,
    runtime: ValidatedResourceEntryView | None,
    inventory: ResourceInventoryEnvelope,
    availability: ResourceAvailabilityEnvelope,
) -> ContractReport:
    """Boundedly exercise a planner with caller-supplied semantic samples."""

    descriptor = _check(
        lambda: (
            getattr(planner, "descriptor").kind == getattr(planner, "resource_kind")
        ),
        "planner descriptor and resource kind agree",
    )
    resolution = _check(
        lambda: planner.resolve_request(authored, runtime),  # type: ignore[attr-defined]
        "planner resolved request",
    )
    opportunity = _check(
        lambda: planner.validate_opportunity(inventory, availability),  # type: ignore[attr-defined]
        "planner validated opportunity",
    )
    findings = [
        _finding("resource_planner.descriptor", descriptor),
        _finding("resource_planner.resolve", resolution),
        _finding("resource_planner.opportunity", opportunity),
    ]
    return ContractReport("loom.scheduling.resource_planner", 1, tuple(findings))


def check_hard_constraint_contract(
    evaluator: object,
    *,
    work: WorkItem,
    candidate: object,
    claims: tuple[object, ...],
    spec: object,
) -> ContractReport:
    result = _check(
        lambda: evaluator.evaluate(work, candidate, claims, spec),  # type: ignore[attr-defined]
        "hard evaluator accepted supplied complete placement",
    )
    typed = result[0] and isinstance(result[1], HardConstraintResult)
    return ContractReport(
        "loom.scheduling.hard_constraint",
        1,
        (
            _finding("hard_constraint.evaluate", result),
            ContractFinding(
                "hard_constraint.result",
                "pass" if typed else "fail",
                "hard evaluator returned HardConstraintResult"
                if typed
                else "hard evaluator returned an invalid result",
            ),
        ),
    )


def check_preference_scorer_contract(
    scorer: object,
    *,
    work: WorkItem,
    candidate: object,
    claims: tuple[object, ...],
    spec: object,
) -> ContractReport:
    result = _check(
        lambda: scorer.evaluate(work, candidate, claims, spec),  # type: ignore[attr-defined]
        "preference scorer accepted supplied complete placement",
    )
    typed = result[0] and isinstance(result[1], PreferenceResult)
    return ContractReport(
        "loom.scheduling.preference_scorer",
        1,
        (
            _finding("preference_scorer.evaluate", result),
            ContractFinding(
                "preference_scorer.result",
                "pass" if typed else "fail",
                "preference scorer returned PreferenceResult"
                if typed
                else "preference scorer returned an invalid result",
            ),
        ),
    )


def check_scheduling_policy_contract(
    policy: object, *, context: PolicyContext
) -> ContractReport:
    result = _check(
        lambda: policy.select(context),  # type: ignore[attr-defined]
        "policy accepted bounded grouped evaluations",
    )
    typed = result[0] and isinstance(result[1], PolicyDecision)
    return ContractReport(
        "loom.scheduling.policy",
        1,
        (
            _finding("scheduling_policy.select", result),
            ContractFinding(
                "scheduling_policy.result",
                "pass" if typed else "fail",
                "policy returned PolicyDecision"
                if typed
                else "policy returned an invalid result",
            ),
        ),
    )


if TYPE_CHECKING:
    from loom.pipeline.event_sinks import EventSinkContext
    from loom.pipeline.events import EventReference, PipelineEventRecord
    from loom.pipeline.execution.models import StageExecutionRequest


def check_codec_contract(
    codec: object,
    *,
    roundtrip_values: Iterable[object],
    metadata_cases: Iterable[tuple[object, Mapping[str, object] | None]] = (),
) -> ContractReport:
    """Check a codec against caller-provided ordinary and metadata samples."""

    cases = tuple((value, None) for value in roundtrip_values) + tuple(metadata_cases)
    protocol = _check(lambda: isinstance(codec, Codec), "codec satisfies Codec")
    key = _check(
        lambda: isinstance(getattr(codec, "key"), str) and bool(getattr(codec, "key")),
        "codec key is a non-empty string",
    )
    findings = [
        _finding("codec.protocol", protocol),
        _finding("codec.key", key),
    ]
    ready = protocol[0] and key[0]
    codec_value = cast(Codec, codec)
    for value, metadata in cases:
        encoded: bytes | None = None
        if ready:
            encoded_result = _check(
                lambda: codec_value.encode(value, metadata=cast(Any, metadata)),
                "codec encoded sample",
            )
            encoded = (
                encoded_result[1]
                if encoded_result[0] and isinstance(encoded_result[1], bytes)
                else None
            )
            findings.append(
                _finding("codec.encode", encoded_result, require_type=bytes)
            )
        else:
            findings.append(
                _failed(
                    "codec.encode",
                    "codec protocol or key check failed; sample was not invoked",
                )
            )
        if encoded is not None:
            encoded_data = encoded
            decoded_result = _check(
                lambda: codec_value.decode(encoded_data, metadata=cast(Any, metadata)),
                "codec decoded sample",
            )
            findings.append(_finding("codec.decode", decoded_result))
            if decoded_result[0]:
                findings.append(
                    _finding(
                        "codec.roundtrip",
                        _check(
                            lambda: decoded_result[1] == value,
                            "decoded value matches sample",
                        ),
                    )
                )
            else:
                findings.append(
                    _failed(
                        "codec.roundtrip",
                        "codec decode failed; roundtrip comparison was not attempted",
                    )
                )
        else:
            findings.append(
                _failed("codec.decode", "codec encode failed; decode was not attempted")
            )
            findings.append(
                _failed(
                    "codec.roundtrip",
                    "codec encode failed; roundtrip comparison was not attempted",
                )
            )
    return ContractReport("loom.codec", 1, tuple(findings))


def check_resource_validator_contract(
    kind: object,
    validator: object,
    *,
    valid_entries: Iterable[ResourceEntry],
    invalid_entries: Iterable[ResourceEntry],
) -> ContractReport:
    """Check a resource validator with caller-provided accepted and rejected entries."""

    valid = tuple(valid_entries)
    invalid = tuple(invalid_entries)
    kind_check = _check(
        lambda: bool(validate_resource_kind(kind)), "resource kind is valid"
    )
    callable_check = _check(
        lambda: callable(validator), "resource validator is callable"
    )
    registration_check = (
        _check(
            lambda: ResourceValidatorRegistry().with_validator(
                cast(str, kind), cast(ResourceValidator, validator)
            ),
            "resource validator registers in an empty registry",
        )
        if kind_check[0] and callable_check[0]
        else (
            False,
            None,
            "resource kind or callable check failed; registration was not attempted",
        )
    )
    findings = [
        _finding("resource_validator.kind", kind_check),
        _finding("resource_validator.callable", callable_check),
        _finding("resource_validator.registration", registration_check),
    ]
    ready = kind_check[0] and callable_check[0] and registration_check[0]
    validator_value = cast(ResourceValidator, validator)
    for entry in valid:
        if ready:
            findings.append(
                _finding(
                    "resource_validator.accepts_valid",
                    _check(
                        lambda entry=entry: validator_value(entry, "valid_entry"),
                        "validator accepted valid entry",
                    ),
                )
            )
        else:
            findings.append(
                _failed(
                    "resource_validator.accepts_valid",
                    "validator prerequisites failed; entry was not invoked",
                )
            )
    for entry in invalid:
        if ready:
            result = _check(
                lambda entry=entry: validator_value(entry, "invalid_entry"),
                "validator rejected invalid entry",
            )
            findings.append(
                ContractFinding(
                    "resource_validator.rejects_invalid",
                    "pass" if not result[0] else "fail",
                    "validator rejected invalid entry"
                    if not result[0]
                    else "validator accepted invalid entry",
                )
            )
        else:
            findings.append(
                _failed(
                    "resource_validator.rejects_invalid",
                    "validator prerequisites failed; entry was not invoked",
                )
            )
    return ContractReport("loom.resource_validator", 1, tuple(findings))


def check_executor_contract(
    executor: object,
    *,
    requests: Iterable["StageExecutionRequest"],
) -> ContractReport:
    """Check an executor's identity and caller-provided execution requests."""

    request_values = tuple(requests)
    protocol = _check(
        lambda: isinstance(executor, Executor), "executor satisfies Executor"
    )
    name = _check(
        lambda: (
            isinstance(getattr(executor, "name"), str)
            and bool(getattr(executor, "name"))
        ),
        "executor name is a non-empty string",
    )
    findings = [
        _finding("executor.protocol", protocol),
        _finding("executor.name", name),
    ]
    ready = protocol[0] and name[0]
    executor_value = cast(Executor, executor)
    for request in request_values:
        if not ready:
            findings.extend(
                (
                    _failed(
                        "executor.execute",
                        "executor protocol or name check failed; request was not invoked",
                    ),
                    _failed("executor.result_type", "executor request was not invoked"),
                    _failed(
                        "executor.result_identity", "executor request was not invoked"
                    ),
                )
            )
            continue
        execution = _check(
            lambda request=request: executor_value.execute(request),
            "executor executed request",
        )
        findings.append(_finding("executor.execute", execution))
        from loom.pipeline.execution.models import StageExecutionResult

        findings.append(
            _finding(
                "executor.result_type", execution, require_type=StageExecutionResult
            )
        )
        if execution[0] and isinstance(execution[1], StageExecutionResult):
            result = execution[1]
            identity = _check(
                lambda: (
                    result.stage_name == request.stage.name
                    and result.attempt == request.attempt
                    and result.executor_name == executor_value.name
                ),
                "executor result matches request and executor identity",
            )
            findings.append(_finding("executor.result_identity", identity))
        else:
            findings.append(
                _failed(
                    "executor.result_identity",
                    "executor did not return StageExecutionResult",
                )
            )
    return ContractReport("loom.executor", 1, tuple(findings))


def check_event_sink_contract(
    sink: object,
    *,
    events: Iterable["PipelineEventRecord | EventReference"],
    context_factory: Callable[
        ["PipelineEventRecord | EventReference"], "EventSinkContext"
    ],
) -> ContractReport:
    """Check a sink registration against caller-provided event/context pairs."""

    from loom.pipeline.event_sinks import EventSinkRegistration, EventSinkSubscription

    event_values = tuple(events)
    registration = sink if isinstance(sink, EventSinkRegistration) else None
    sink_value = registration.sink if registration is not None else sink
    callable_check = _check(lambda: callable(sink_value), "event sink is callable")
    findings = [_finding("event_sink.callable", callable_check)]
    subscription_check = _check(
        lambda: (
            registration is None
            or registration.subscription is None
            or isinstance(registration.subscription, EventSinkSubscription)
        ),
        "event sink subscription selects exact event names",
    )
    findings.append(_finding("event_sink.subscription", subscription_check))
    callback = cast(Callable[[object, object], object], sink_value)
    for event in event_values:
        event_type = getattr(event, "event_type", None)
        should_dispatch = (
            registration is None
            or registration.subscription is None
            or event_type in registration.subscription.event_types
        )
        if callable_check[0] and subscription_check[0] and should_dispatch:
            invocation = _check(
                lambda event=event: callback(event, context_factory(event)),
                "event sink accepted event and context",
            )
            findings.append(_finding("event_sink.invoke", invocation))
        elif should_dispatch:
            findings.append(
                _failed(
                    "event_sink.invoke",
                    "event sink callable check failed; event was not invoked",
                )
            )
    return ContractReport("loom.event_sink", 2, tuple(findings))


def _check(
    operation: Callable[[], Any], message: str
) -> tuple[bool, object | None, str]:
    try:
        result = operation()
    except (
        Exception
    ) as exc:  # Trusted caller samples; reports retain bounded exception facts.
        return (
            False,
            None,
            f"{message}: {type(exc).__name__}: {str(exc) or type(exc).__name__}",
        )
    if result is False:
        return False, result, f"{message}: returned false"
    return True, result, message


def _finding(
    code: str,
    check: tuple[bool, object | None, str],
    *,
    require_type: type[object] | None = None,
) -> ContractFinding:
    passed, value, message = check
    if passed and require_type is not None and not isinstance(value, require_type):
        return ContractFinding(
            code,
            "fail",
            f"{message}: returned {type(value).__name__}, expected {require_type.__name__}",
        )
    return ContractFinding(code, "pass" if passed else "fail", message)


def _failed(code: str, message: str) -> ContractFinding:
    return ContractFinding(code, "fail", message)
