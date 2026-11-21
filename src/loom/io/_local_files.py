"""Descriptor-relative opens for protected local storage."""

import os
from pathlib import Path, PurePosixPath


def open_member_descriptor(root: Path, member: str) -> int:
    """Open one selected member without following symbolic links."""
    relative = PurePosixPath(member)
    if not root.is_absolute() or relative.is_absolute() or not relative.parts:
        raise ValueError("protected file access requires an absolute root and a relative file")
    if ".." in root.parts or ".." in relative.parts:
        raise ValueError("protected file paths cannot traverse parents")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root.anchor, directory_flags)
    try:
        for part in (*root.parts[1:], *relative.parts[:-1]):
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(
            relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    finally:
        os.close(directory)
