"""Unit tests for unsupported Phase 1 stubs."""

import loom.config
import loom.errors


def test_loom_config_stubs_raise_config_error() -> None:
    expected_messages = {
        loom.config.compose_config: "Phase 4",
        loom.config.instantiate: "Phase 4",
        loom.config.register_recipe: "Phase 5",
    }
    for stub in (loom.config.compose_config, loom.config.instantiate, loom.config.register_recipe):
        try:
            stub()
        except Exception as exc:  # noqa: BLE001
            assert isinstance(exc, loom.errors.ConfigError)
            assert isinstance(exc, loom.errors.LoomError)
            assert "not implemented" in str(exc)
            assert expected_messages[stub] in str(exc)
            continue
        raise AssertionError(f"Expected {stub.__name__} to raise ConfigError")


def test_loom_config_stubs_allow_arguments() -> None:
    assert _raises_config_error(loom.config.compose_config, arg=1) is True
    assert _raises_config_error(loom.config.instantiate, "a", key="b") is True
    assert _raises_config_error(loom.config.register_recipe, object()) is True


def _raises_config_error(func, *args, **kwargs) -> bool:
    try:
        func(*args, **kwargs)
    except loom.errors.ConfigError as exc:
        assert "not implemented" in str(exc)
        return True
    except Exception as exc:
        raise AssertionError(f"Expected ConfigError, got {type(exc).__name__}") from exc
    raise AssertionError(f"Expected ConfigError from {func.__name__}")
