"""Package-level API tests for event sink contracts."""

import pytest


pytestmark = pytest.mark.package


def test_pipeline_event_sinks_public_exports() -> None:
    import loom.pipeline.event_sinks as event_sinks

    assert set(event_sinks.__all__) == {
        "EVENT_SINK_FAILURE_SCHEMA_VERSION",
        "EVENT_OBSERVER_LINK_SCHEMA_VERSION",
        "EventSinkError",
        "EventSinkRegistryError",
        "EventObserverExternalRef",
        "EventSinkFailureRecord",
        "EventObserverLinkRecord",
        "EventObserverLinkRecorder",
        "EventSinkFailureRecorder",
        "EventSinkContext",
        "EventSink",
        "EventSinkCallbackResult",
        "EventSinkDispatchResult",
        "EventSinkRegistry",
    }
