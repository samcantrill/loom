"""Unit tests for unsupported Phase 5 stubs."""

import loom.config
import loom.errors


def test_loom_config_stubs_raise_config_error() -> None:
    expected_messages = {
        loom.config.instantiate: "Phase 5",
        loom.config.register_recipe: "Phase 5",
    }
    for stub in (loom.config.instantiate, loom.config.register_recipe):
        try:
            stub()
        except Exception as exc:  # noqa: BLE001
            assert isinstance(exc, loom.errors.ConfigError)
            assert isinstance(exc, loom.errors.LoomError)
            assert "not supported" in str(exc)
            assert expected_messages[stub] in str(exc)
            continue
        raise AssertionError(f"Expected {stub.__name__} to raise ConfigError")
