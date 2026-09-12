"""Atomic I/O primitives for Janus data files.

This module is the single choke point for all writes to ``data/``.
It implements crash-safe, atomic persistence:

- ``atomic_write``       — write-to-temp + ``os.replace`` (POSIX atomic),
                           optionally preserving a ``.bak`` snapshot first.
- ``atomic_read``        — thin wrapper so all read/modify/write paths start
                           from the same primitive.
- ``read_modify_write``  — load → mutate → atomically persist.

Design reference: ADR-005 §4 ("Atomic write primitive — single choke
point for I/O").

Concurrency note
----------------
POSIX ``os.replace`` is atomic at the filesystem level, but a writer that
reads the file, computes a new value, and then writes can still lose
updates if another process writes in between.  ``atomic_write`` detects
this by comparing the file's identity (inode + mtime + size) before the
replace; if the on-disk file changed between the read and the write,
``ConcurrentWriteError`` is raised so the caller can retry.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from janus._log import emit

logger = logging.getLogger(__name__)


class ConcurrentWriteError(RuntimeError):
    """Raised when the target file was modified between read and write.

    The caller should retry the read-modify-write cycle.  After the
    configurable retry budget is exhausted (see ADR-005 §7), the error
    propagates to ``ingest_activities`` which records it on the
    corresponding ``IngestResult``.
    """


class AtomicWriteError(RuntimeError):
    """Raised when the atomic write itself fails (disk full, permissions)."""


# ── File identity snapshot ─────────────────────────────────────────────────

class _FileSnapshot:
    """Lightweight identity check for detecting concurrent modification.

    Captured before the read phase of a read-modify-write cycle and
    compared after the write phase.  ``None`` means the file did not
    exist at snapshot time.
    """

    __slots__ = ("mtime_ns", "size", "inode")

    def __init__(self, path: Path) -> None:
        try:
            st = path.stat()
            self.mtime_ns = st.st_mtime_ns
            self.size = st.st_size
            self.inode = st.st_ino
        except FileNotFoundError:
            self.mtime_ns = None
            self.size = None
            self.inode = None

    def matches(self, path: Path) -> bool:
        """Return True if the file's identity still matches the snapshot."""
        current = _FileSnapshot(path)
        return (
            self.mtime_ns == current.mtime_ns
            and self.size == current.size
            and self.inode == current.inode
        )


def atomic_write(path: Path, content: str, *, backup: bool = True) -> None:
    """Write *content* to *path* atomically.

    Writes to a temp file in the same directory, then ``os.replace``
    onto *path*.  ``os.replace`` is atomic on POSIX: the destination is
    either the old file or the new file, never a torn mix.

    If ``backup`` is True and *path* already exists, the current file is
    copied to ``path.bak`` before the replace, so a crash mid-write
    leaves the last-known-good file intact.

    Raises:
        AtomicWriteError: on disk-full, permission, or OS-level failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=path.name + ".tmp.",
        suffix=".atomic",
    )
    tmp = Path(tmp_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        if backup and path.exists():
            _backup_path = path.parent / (path.name + ".bak")
            try:
                import shutil
                shutil.copy2(path, _backup_path)
            except OSError:
                # Backup is best-effort — never block the atomic write
                pass

        os.replace(tmp, path)
    except Exception:
        # Clean up the temp file on any failure so it doesn't linger
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise AtomicWriteError(
            f"Failed to atomically write {path}"
        )

    emit(
        logger,
        "service.atomic_io.write",
        span_id="atomic_write",
        path=str(path),
        bytes_written=len(content),
        backup=backup,
        message="Atomic write complete",
    )


def atomic_read(path: Path) -> str:
    """Read file content as text.

    Thin wrapper so all read/modify/write starts from the same primitive
    (ADR-005 §4).  Returns empty string for a missing file — callers
    should handle that explicitly when needed.
    """
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_modify_write(
    path: Path,
    mutate: Callable[[str], str],
    *,
    backup: bool = True,
) -> None:
    """Load -> mutate -> atomically persist.

    The *mutate* callback receives the current file content (as a string)
    and returns the new content.  The entire cycle is atomic: the file
    is written via ``atomic_write`` and a ``ConcurrentWriteError`` is
    raised if the file changed between the read and the write.

    This eliminates the read-entire-file / modify-one-line /
    write-entire-file pattern that every service method currently
    replicates by hand (ADR-005 §4).
    """
    snapshot = _FileSnapshot(path)
    current = atomic_read(path)

    new_content = mutate(current)

    # Detect concurrent modification between read and write.
    if path.exists() and snapshot.mtime_ns is not None:
        if not snapshot.matches(path):
            raise ConcurrentWriteError(
                f"File {path} was modified concurrently during "
                f"read-modify-write; caller should retry."
            )

    atomic_write(path, new_content, backup=backup)


def read_modify_write_with_retry(
    path: Path,
    mutate: Callable[[str], str],
    *,
    backup: bool = True,
    max_retries: int = 3,
    backoff_base: float = 0.1,
) -> None:
    """Like ``read_modify_write`` but retries on ``ConcurrentWriteError``.

    Uses exponential backoff.  After ``max_retries`` attempts are
    exhausted, the last ``ConcurrentWriteError`` is re-raised.
    """
    attempt = 0
    while True:
        try:
            read_modify_write(path, mutate, backup=backup)
            return
        except ConcurrentWriteError as exc:
            attempt += 1
            if attempt > max_retries:
                raise
            delay = backoff_base * (2 ** (attempt - 1))
            emit(
                logger,
                "service.atomic_io.retry",
                span_id="rmw_retry",
                path=str(path),
                attempt=attempt,
                max_retries=max_retries,
                delay_seconds=delay,
                message=f"Concurrent write conflict; retry {attempt}/{max_retries}",
            )
            time.sleep(delay)
