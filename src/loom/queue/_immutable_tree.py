"""Reuse a complete content audit only for a pinned kernel snapshot with no submounts."""
from __future__ import annotations

from collections import OrderedDict
import os
from pathlib import Path
import re
import stat
from threading import Lock

from loom.pipeline.stores import shared_artifacts as shared
from loom.pipeline.stores.errors import ArtifactStoreError


_guard = Lock()
_verified: OrderedDict[tuple, int] = OrderedDict()


def _mount_id(fd):
    for line in Path(f"/proc/self/fdinfo/{fd}").read_bytes().splitlines():
        if line.startswith(b"mnt_id:"):
            return int(line.split()[1])
    return None


def _snapshot(fd):
    # A read-only bind of an ordinary filesystem can still change via another path.
    try:
        if not os.fstatvfs(fd).f_flag & os.ST_RDONLY:
            return None
        mount_id = _mount_id(fd)
        root = os.readlink(os.fsencode(f"/proc/self/fd/{fd}"))
        mounts = Path("/proc/self/mountinfo").read_bytes().splitlines()
    except OSError:
        return None
    recognized = False
    for line in mounts:
        fields, fs = line.split(b" - ", 1)
        parts = fields.split()
        if int(parts[0]) == mount_id:
            recognized = fs.split()[0] == b"squashfs"
            continue
        mountpoint = re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m[1], 8)]), parts[4])
        if mountpoint == root or mountpoint.startswith(root.rstrip(b"/") + b"/"):
            return None
    return mount_id if recognized else None


def _audit(fd, mount_id, members, limits):
    def unreadable(exc):
        raise exc

    seen = set()
    total = 0
    for directory, dirs, files, parent in os.fwalk(".", dir_fd=fd, follow_symlinks=False, onerror=unreadable):
        if _mount_id(parent) != mount_id:
            return False
        if any(not stat.S_ISDIR(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode) for name in dirs):
            raise ArtifactStoreError("snapshot contains an unsupported directory")
        for name in files:
            path = (Path(directory) / name).as_posix()
            if path == shared.RECEIPT:
                continue
            expected = members.get(path)
            if expected is None:
                raise ArtifactStoreError("snapshot contains an undeclared member")
            member = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
            try:
                if _mount_id(member) != mount_id:
                    return False
                size, digest = shared.descriptor_identity(member, max_bytes=limits["max_payload_bytes"],
                                                          preceding_bytes=total)
            finally:
                os.close(member)
            if size != expected["size_bytes"] or digest != expected["digest"]:
                raise ArtifactStoreError("snapshot member differs from declaration")
            seen.add(path)
            total += size
    if seen != members.keys():
        raise ArtifactStoreError("snapshot lacks a declared member")
    return True


def verified(root, declaration, members, limits):
    """Return False to request a fresh ordinary inventory on unsupported storage."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        mount_id = _snapshot(fd)
        if mount_id is None:
            return False
        info = os.fstat(fd)
        key = (mount_id, info.st_dev, info.st_ino, declaration, tuple(sorted(limits.items())))
        with _guard:
            if key in _verified:
                _verified.move_to_end(key)
                return True
        if not _audit(fd, mount_id, members, limits) or _snapshot(fd) != mount_id:
            return False
        with _guard:
            if key not in _verified:
                _verified[key] = os.dup(fd)  # Pin the mount and inode across requests.
                if len(_verified) > 8:
                    os.close(_verified.popitem(last=False)[1])
        return True
    finally:
        os.close(fd)
