"""Private filesystem ownership locks for one local authority service."""

from __future__ import annotations

from contextlib import AbstractContextManager
import fcntl
from pathlib import Path
from typing import TextIO


class AuthorityServiceLockError(RuntimeError):
    """Raised when another authority lifecycle or service owner holds a root."""


class AuthorityServiceLocks(AbstractContextManager["AuthorityServiceLocks"]):
    """Exclusive process-lifetime ownership of an authority state root and workspace."""

    def __init__(self, state_lock: TextIO, workspace_lock: TextIO) -> None:
        self._state_lock = state_lock
        self._workspace_lock = workspace_lock

    @classmethod
    def acquire(
        cls, *, state_dir: Path, workspace_root: Path
    ) -> "AuthorityServiceLocks":
        return cls(*_acquire(*_service_lock_paths(state_dir, workspace_root)))

    @classmethod
    def adopt(
        cls, *, state_lock_fd: int, workspace_lock_fd: int
    ) -> "AuthorityServiceLocks":
        return cls(
            _open_inherited_lock(state_lock_fd),
            _open_inherited_lock(workspace_lock_fd),
        )

    @staticmethod
    def ensure_unowned(*, state_dir: Path | None, workspace_root: Path) -> None:
        """Reject a live bootstrap owner even before its state is published."""

        locks = _acquire(*_service_lock_paths(state_dir, workspace_root))
        for lock in reversed(locks):
            lock.close()

    @property
    def state_lock_fd(self) -> int:
        return self._state_lock.fileno()

    @property
    def workspace_lock_fd(self) -> int:
        return self._workspace_lock.fileno()

    def close(self) -> None:
        self._workspace_lock.close()
        self._state_lock.close()

    def __exit__(self, *_args: object) -> None:
        self.close()


class AuthorityLifecycleLocks(AbstractContextManager["AuthorityLifecycleLocks"]):
    """Short-lived command serialization for one authority state root and workspace."""

    def __init__(self, locks: tuple[TextIO, ...]) -> None:
        self._locks = locks

    @classmethod
    def acquire(
        cls,
        *,
        state_dir: Path | None,
        workspace_root: Path,
    ) -> "AuthorityLifecycleLocks":
        paths = [_workspace_lifecycle_lock_path(workspace_root)]
        if state_dir is not None:
            paths.append(_state_lifecycle_lock_path(state_dir))
        return cls(_acquire(*paths))

    def close(self) -> None:
        for lock in reversed(self._locks):
            lock.close()

    def __exit__(self, *_args: object) -> None:
        self.close()


def _service_lock_paths(
    state_dir: Path | None, workspace_root: Path
) -> tuple[Path, ...]:
    paths = [workspace_root.resolve() / ".loom" / "authority" / "service.lock"]
    if state_dir is not None:
        paths.append(state_dir.resolve() / "authority-service.lock")
    return tuple(paths)


def _state_lifecycle_lock_path(state_dir: Path) -> Path:
    return state_dir.resolve() / "authority-lifecycle.lock"


def _workspace_lifecycle_lock_path(workspace_root: Path) -> Path:
    return workspace_root.resolve() / ".loom" / "authority" / "lifecycle.lock"


def _acquire(*paths: Path) -> tuple[TextIO, ...]:
    opened: list[TextIO] = []
    try:
        for path in sorted(paths, key=lambda item: str(item)):
            path.parent.mkdir(parents=True, exist_ok=True)
            lock = path.open("a+", encoding="utf-8")
            lock_path_mode = 0o600
            path.chmod(lock_path_mode)
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                lock.close()
                raise AuthorityServiceLockError(
                    f"authority root is already owned: {path.parent}"
                ) from exc
            opened.append(lock)
    except BaseException:
        for lock in reversed(opened):
            lock.close()
        raise
    return tuple(opened)


def _open_inherited_lock(fd: int) -> TextIO:
    try:
        return open(fd, "a+", encoding="utf-8", closefd=True)
    except OSError as exc:
        raise AuthorityServiceLockError(
            "authority service lock inheritance failed"
        ) from exc


__all__ = [
    "AuthorityLifecycleLocks",
    "AuthorityServiceLockError",
    "AuthorityServiceLocks",
]
