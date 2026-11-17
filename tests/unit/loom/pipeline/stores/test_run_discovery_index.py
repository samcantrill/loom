"""Discovery registration survives interrupted publication and concurrent refresh."""

from pathlib import Path

import pytest

from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.pipeline.stores import _run_discovery_index as index
from loom.pipeline.stores import local_runs

pytestmark = pytest.mark.unit


def rows(root):
    with index.connection(root) as conn:
        return {row['run_uri']: dict(row) for row in conn.execute('SELECT * FROM discovery_runs')}


def test_registration_precedes_publication_and_refresh_recovers_interruption(tmp_path, monkeypatch):
    root = tmp_path / 'runs'
    uri = path_to_run_uri(root / 'one')
    original = local_runs.atomic_write_json

    def interrupted(path, value, *args, **kwargs):
        if path.name == 'run.json':
            assert rows(root)[uri]['pending'] == 1
            raise OSError('interrupted before document publication')
        return original(path, value, *args, **kwargs)

    monkeypatch.setattr(local_runs, 'atomic_write_json', interrupted)
    with pytest.raises(OSError, match='interrupted'):
        LocalRunStore(root).create_run(uri)
    assert index.refresh(root)
    assert rows(root)[uri]['pending'] == 1
    monkeypatch.setattr(local_runs, 'atomic_write_json', original)
    LocalRunStore(root).ensure_run(uri)
    assert rows(root)[uri]['pending'] == 0
    assert index.refresh(root) == ()


def test_external_copy_requires_refresh_and_external_deletion_is_pruned(tmp_path):
    import shutil

    source, target = tmp_path / 'source', tmp_path / 'target'
    source_uri = path_to_run_uri(source / 'one')
    LocalRunStore(source).create_run(source_uri)
    target.mkdir()
    # A supported copy must retain a correctly addressed run document.
    target_uri = path_to_run_uri(target / 'one')
    shutil.copytree(source / 'one', target / 'one')
    import json
    path = target / 'one/run.json'
    document = json.loads(path.read_text())
    document['run_uri'] = target_uri
    path.write_text(json.dumps(document))
    assert not index.index_path(target).exists()
    assert index.refresh(target) == ()
    assert set(rows(target)) == {target_uri}
    shutil.rmtree(target / 'one')
    assert index.refresh(target) == ()
    assert rows(target) == {}


def test_refresh_finishes_registration_when_writer_dies_after_publication(tmp_path, monkeypatch):
    root = tmp_path / 'runs'
    uri = path_to_run_uri(root / 'one')
    original = index.register

    def interrupted(root, run_uri, created_at, *, published):
        if published:
            raise OSError('interrupted after document publication')
        return original(root, run_uri, created_at, published=False)

    monkeypatch.setattr(index, 'register', interrupted)
    with pytest.raises(OSError, match='after document'):
        LocalRunStore(root).create_run(uri)
    assert (root / 'one/run.json').is_file() and rows(root)[uri]['pending'] == 1
    assert index.refresh(root) == ()
    assert rows(root)[uri]['pending'] == 0


def test_refresh_ignores_auxiliary_directories_without_run_documents(tmp_path):
    root = tmp_path / 'runs'
    uri = path_to_run_uri(root / 'one')
    LocalRunStore(root).create_run(uri)
    for name in ('.loom', 'loom-artifacts', 'loom-work', 'custom-shared-storage'):
        (root / name).mkdir()
    assert index.refresh(root) == ()
    assert set(rows(root)) == {uri}
    with index.connection(root) as conn:
        assert conn.execute('SELECT refreshed FROM discovery_metadata').fetchone()[0] == 1


def test_refresh_retains_registered_run_with_missing_document(tmp_path):
    root = tmp_path / 'runs'
    uri = path_to_run_uri(root / 'one')
    LocalRunStore(root).create_run(uri)
    (root / 'one/run.json').unlink()
    assert index.refresh(root) == ({'code': 'discovery_record_unavailable', 'run_uri': uri},)
    assert set(rows(root)) == {uri}


def test_refresh_reports_unregistered_corrupt_run_document(tmp_path):
    root = tmp_path / 'runs'
    run = root / 'copied'
    run.mkdir(parents=True)
    (run / 'run.json').write_text('{unfinished')
    assert index.refresh(root) == (
        {'code': 'discovery_record_unavailable', 'run_uri': path_to_run_uri(run)},
    )


def test_concurrent_registration_is_not_removed_by_refresh(tmp_path, monkeypatch):
    root = tmp_path / 'runs'
    store = LocalRunStore(root)
    one, two = (path_to_run_uri(root / name) for name in ('one', 'two'))
    store.create_run(one)
    original = Path.iterdir

    def enumerate_before_new_registration(path):
        entries = list(original(path))
        if path == root:
            store.create_run(two)
        return iter(entries)

    monkeypatch.setattr(Path, 'iterdir', enumerate_before_new_registration)
    assert index.refresh(root) == ()
    assert set(rows(root)) == {one, two}


def test_failed_enumeration_does_not_prune_registered_runs(tmp_path, monkeypatch):
    root = tmp_path / 'runs'
    uri = path_to_run_uri(root / 'one')
    LocalRunStore(root).create_run(uri)

    def unavailable(path):
        raise OSError('storage unavailable')

    monkeypatch.setattr(Path, 'iterdir', unavailable)
    with pytest.raises(index.RunProjectionError, match='enumeration failed'):
        index.refresh(root)
    assert set(rows(root)) == {uri}


def test_public_discovery_refresh_does_not_acquire_live_summaries(tmp_path, monkeypatch):
    from loom.runs import RunCatalog
    from loom.runs import _scan

    root = tmp_path / 'runs'
    uri = path_to_run_uri(root / 'one')
    LocalRunStore(root).create_run(uri)

    def forbidden(*args, **kwargs):
        pytest.fail('discovery-only refresh acquired lifecycle summaries')

    monkeypatch.setattr(_scan, 'scan_current_collection_records', forbidden)
    result = RunCatalog.open(root).rebuild(discovery_only=True)
    assert result.indexed_count == 1 and not result.warnings
    assert not (root / '.loom_catalog/catalog.sqlite').exists()
    from loom.runs import RunQuery, CollectionScope, Order
    page = RunCatalog.open(root).search(RunQuery(scope=CollectionScope(), order_by=(Order('submitted_at'),)))
    assert not page.complete
    assert any(warning['code'] == 'sort_fact_unavailable' for warning in page.warnings)
