"""Qualified runtime inventory publication preserves recovery and operator edits."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from loom.fleet import _inventory_publication as publication
from loom.fleet._host import atomic, read
from loom.queue.errors import QueueConflictError


@pytest.fixture
def operation(tmp_path):
    inventory = tmp_path / "fleet.yaml"
    inventory.write_text(
        "name: research\nruntime_release: releases/old.json\n"
        "service_manager: tmux\nagents: {worker: {host: machine, config: agent.yaml}}\n"
    )
    inventory.chmod(0o600)
    before = hashlib.sha256(inventory.read_bytes()).hexdigest()
    target = tmp_path / "releases/new.json"
    selection = publication.bind(SimpleNamespace(path=inventory), target, before)
    directory = tmp_path / "operation"
    directory.mkdir(mode=0o700)
    receipts = directory / "steps"
    receipts.mkdir(mode=0o700)
    events = []
    return SimpleNamespace(
        directory=directory, receipts=receipts,
        intent={"inventory_publication": selection},
        gate=lambda: events.append("gate-closed"),
        recheck=lambda: events.append("checked"),
        events=events,
    )


def test_inventory_publish_preserves_fields_and_mode_and_replays(operation):
    selection = operation.intent["inventory_publication"]
    path = Path(selection["path"])
    original = yaml.safe_load(path.read_text())
    publication.publish(operation)
    published = yaml.safe_load(path.read_text())
    assert published == {**original, "runtime_release": selection["after"]["runtime_release"]}
    assert path.stat().st_mode & 0o777 == 0o600
    assert operation.events[:2] == ["gate-closed", "checked"]
    assert read(operation.directory / "accepted-inputs.json") == {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
    }
    stat = path.stat()
    publication.publish(operation)
    assert path.stat().st_ino == stat.st_ino
    assert path.stat().st_mtime_ns == stat.st_mtime_ns


def test_publish_recovers_replace_before_receipt(operation, monkeypatch):
    target = Path(operation.intent["inventory_publication"]["path"])
    replace = publication.os.replace

    def lost_reply(source, destination):
        replace(source, destination)
        if Path(destination) == target:
            raise OSError("lost inventory publication reply")

    with monkeypatch.context() as patch:
        patch.setattr(publication.os, "replace", lost_reply)
        with pytest.raises(OSError, match="lost inventory"):
            publication.publish(operation)
    assert not (operation.directory / "accepted-inputs.json").exists()
    publication.reconcile(operation)
    publication.publish(operation)
    assert read(operation.receipts / "publish-inventory/receipt.json")["state"] == "published"


@pytest.mark.parametrize("boundary", ["before", "staging", "after"])
def test_independent_inventory_edit_is_preserved(operation, monkeypatch, boundary):
    target = Path(operation.intent["inventory_publication"]["path"])
    changed = b'{"name":"independently edited"}'
    if boundary == "after":
        publication.publish(operation)
    if boundary == "staging":
        create = publication.os.open

        def edit_while_staging(*args, **kwargs):
            result = create(*args, **kwargs)
            if Path(args[0]).name.startswith(".fleet-inventory-"):
                target.write_bytes(changed)
            return result

        monkeypatch.setattr(publication.os, "open", edit_while_staging)
    else:
        target.write_bytes(changed)
    with pytest.raises(QueueConflictError, match="inventory changed"):
        publication.publish(operation)
    assert target.read_bytes() == changed


def test_matching_target_without_dispatched_publication_is_not_adopted(operation):
    selection = operation.intent["inventory_publication"]
    Path(selection["path"]).write_text(json.dumps(selection["after"], sort_keys=True))
    with pytest.raises(QueueConflictError, match="independently"):
        publication.reconcile(operation)


def test_interrupted_staging_is_reused_and_removed_on_resume(operation):
    selection = operation.intent["inventory_publication"]
    target = Path(selection["path"])
    identity = hashlib.sha256(str(operation.directory).encode()).hexdigest()
    temporary = target.parent / f".fleet-inventory-{identity}.tmp"
    temporary.write_bytes(b"partial inventory left by a killed publisher")
    publication.publish(operation)
    assert not temporary.exists()
    assert hashlib.sha256(target.read_bytes()).hexdigest() == selection["after_sha256"]


def test_publication_preserves_other_accepted_inputs(operation):
    atomic(operation.directory / "accepted-inputs.json", {"/machine.env": "published-settings"})
    publication.publish(operation)
    assert read(operation.directory / "accepted-inputs.json")["/machine.env"] == "published-settings"


def test_historical_operation_has_no_implicit_inventory_write(tmp_path):
    operation = SimpleNamespace(intent={})
    publication.reconcile(operation)
    publication.publish(operation)
    assert not list(tmp_path.iterdir())
