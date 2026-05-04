import pytest
from pathlib import Path


def _is_optional_selected(config: pytest.Config) -> bool:
    mark_expr = config.getoption("markexpr") or ""
    compact = "".join(mark_expr.split())
    if "optional_dependency" not in compact:
        return False
    return "notoptional_dependency" not in compact


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not _is_optional_selected(config):
        return
    optional_root = Path(__file__).resolve().parent
    pipeline_config_test = (optional_root.parent / "pipeline" / "test_pipeline_config.py").resolve()
    for item in items:
        item_path = Path(item.path).resolve()
        if item_path.is_relative_to(optional_root) or item_path == pipeline_config_test:
            item.add_marker(pytest.mark.optional_dependency)


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    optional_root = Path(__file__).resolve().parent
    candidate = Path(collection_path).resolve()
    pipeline_config_test = (optional_root.parent / "pipeline" / "test_pipeline_config.py").resolve()
    if _is_optional_selected(config):
        return False
    if candidate.is_relative_to(optional_root):
        return True
    return candidate == pipeline_config_test
