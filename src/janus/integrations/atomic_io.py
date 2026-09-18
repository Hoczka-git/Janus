"""Atomic I/O primitives for Janus data files.

This module is the single choke point for all writes to ``data/``.
It implements crash-safe, atomic persistence:

- ``atomic_write``       — write-to-temp + ``os.replace`` (POSIX atomic),
                           optionally preserving a ``.bak`` snapshot first.
                           Opt-in: ``lock``, ``verify``, ``backup_rotation``.
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

import contextlib
import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

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


class HashConflictError(ConcurrentWriteError):
    """Raised when a content-hash-based conflict is detected.

    A :class:`ConcurrentWriteError` subtype: the file's SHA-256 on disk differs
    from the ``expected_hash`` captured by the caller at load time.  Raised by
    :func:`atomic_write` when ``expected_hash`` is supplied and
    :func:`read_modify_write` / :func:`read_modify_write_with_retry` (which
    capture the load-time hash automatically).

    ADR-005 Amendment 01 folds the legacy ``data_protection.detect_conflict``
    SHA-256 check into this primitive so the single choke point carries
    content-hash-based conflict detection as its default (Augmentation 01).
    """


# ── Content-hash conflict detection (ADR-005 Amendment 01) ──────────────────

def compute_content_hash(content: str) -> str:
    """Compute the SHA-256 hash of a string's UTF-8 encoding."""
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_file_hash(path: Path) -> str:
    """Compute the SHA-256 hash of a file's contents.

    Raises :class:`FileNotFoundError` if the file does not exist.
    """
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_hash_conflict(path: Path, expected_hash: str | None) -> bool:
    """Return True if *path*'s current content SHA-256 differs from
    *expected_hash*.

    - Missing file or ``expected_hash is None`` → no conflict (``False``).
    - Otherwise compares the on-disk content hash to *expected_hash*.

    This is the content-hash-based conflict detector that
    :func:`atomic_write` uses by default when ``expected_hash`` is supplied
    (replacing/augmenting the inode/mtime/size snapshot).
    """
    if not path.exists() or expected_hash is None:
        return False
    current_hash = compute_file_hash(path)
    return current_hash != expected_hash


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


@contextlib.contextmanager
def _no_lock() -> Iterator[None]:
    """A no-op context manager used when locking is disabled."""
    yield


def _file_lock(path: Path, *, timeout: float = 5.0):
    """Acquire an exclusive advisory lock on *path*.

    Uses ``fcntl.flock`` (POSIX advisory locking) to prevent concurrent writes
    to the same file.  This guards against CLI + Hermes sync running
    simultaneously.

    Returns a context manager that releases the lock on exit.
    """

    @contextlib.contextmanager
    def _ctx():
        try:
            import fcntl
        except ImportError:
            # Not on a POSIX platform — lock is a no-op
            yield
            return

        lock_fd = open(path, "a")
        try:
            start = time.monotonic()
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (IOError, OSError):
                    if time.monotonic() - start >= timeout:
                        raise TimeoutError(
                            f"Could not acquire lock on {path} within {timeout}s"
                        )
                    time.sleep(0.05)
            yield
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except (IOError, OSError):
                pass
            lock_fd.close()

    return _ctx()


def _post_write_verify(path: Path, expected_content: str) -> bool:
    """Re-read *path* after a write and compare to *expected_content*.

    Returns True on match, False on mismatch or if the file is missing.
    """
    if not path.exists():
        return False
    actual = path.read_text(encoding="utf-8")
    return actual == expected_content


def _rotate_backups(path: Path, *, max_backups: int = 3) -> None:
    """Keep at most *max_backups* rotating ``.bak`` files for *path*.

    Existing backups are renumbered so the newest is ``.bak`` and older ones
    gain a numeric suffix (`.bak.1`, `.bak.2`, ...).  Backups beyond
    *max_backups* are removed.
    """
    backup_path = path.parent / (path.name + ".bak")
    # Gather all .bak / .bak.N variants, newest first
    backups = sorted(
        path.parent.glob(path.name + ".bak*"),
        key=lambda p: p.stat().st_mtime,
    )
    if backup_path.exists():
        # If a current .bak exists, promote it to .bak.1 (and shift the rest up)
        numbered = path.parent / (path.name + ".bak.1")
        # Find the next free slot by shifting existing numbered backups
        for existing in list(backups):
            if existing == backup_path:
                dest = numbered
            else:
                parts = existing.name.split(".bak")
                if len(parts) < 2 or not parts[-1].isdigit():
                    continue
                idx = int(parts[-1]) + 1
                dest = path.parent / (path.name + f".bak.{idx}")
            try:
                existing.rename(dest)
            except OSError:
                pass
    # Prune excess (keep newest max_backups)
    all_backups = sorted(
        path.parent.glob(path.name + ".bak*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in all_backups[max_backups:]:
        try:
            old.unlink()
        except OSError:
            pass


def atomic_write(
    path: Path,
    content: str,
    *,
    backup: bool = True,
    lock: bool = False,
    verify: bool = False,
    backup_rotation: bool = False,
    expected_hash: str | None = None,
) -> None:
    """Write *content* to *path* atomically.

    Writes to a temp file in the same directory, then ``os.replace``
    onto *path*.  ``os.replace`` is atomic on POSIX: the destination is
    either the old file or the new file, never a torn mix.

    If ``backup`` is True and *path* already exists, the current file is
    copied to ``path.bak`` before the replace, so a crash mid-write
    leaves the last-known-good file intact.

    Opt-in safety features (all default to False — no behavior change to
    existing callers):

    - ``lock``:  acquire an exclusive ``fcntl.flock`` advisory lock for the
      duration of the write, preventing concurrent processes from writing
      simultaneously.
    - ``verify``: re-read the file after the replace and compare to
      *content*; raises ``AtomicWriteError`` on mismatch.
    - ``backup_rotation``: when creating a ``.bak``, rotate existing
      backups so at most ``max_backups`` (default 3) are retained.
    - ``expected_hash``: SHA-256 hash of the file's content *at load time*.
      When supplied and the on-disk file has been modified since (its
      current content hash differs), :class:`HashConflictError` (a
      :class:`ConcurrentWriteError`) is raised *before* any write occurs.
      This is the content-hash-based conflict detection that augments the
      inode/mtime/size snapshot used by :func:`read_modify_write`
      (ADR-005 Amendment 01, Augmentation 01).  Pass ``None`` (the default)
      to disable hash-based conflict detection for this write.

    Raises:
        HashConflictError: if *expected_hash* was supplied and the on-disk
            file's content hash differs (only when ``lock`` is not held —
            the lock serializes writers so a locked write skips the race).
        AtomicWriteError: on disk-full, permission, OS-level failure,
            or post-write verification mismatch.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Content-hash-based conflict detection (Augmentation 01).  Skipped under
    # an exclusive lock because the lock already serializes concurrent writers,
    # and the snapshot check in read_modify_write covers the residual race.
    if expected_hash is not None and not lock and detect_hash_conflict(
        path, expected_hash
    ):
        current_hash = compute_file_hash(path)
        raise HashConflictError(
            f"Hash conflict for {path}: expected {expected_hash}, "
            f"got {current_hash}"
        )

    lock_cm = _file_lock(path) if lock else _no_lock()

    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=path.name + ".tmp.",
        suffix=".atomic",
    )
    tmp = Path(tmp_path)
    try:
        with lock_cm:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            if backup and path.exists():
                _backup_path = path.parent / (path.name + ".bak")
                if backup_rotation:
                    _rotate_backups(path, max_backups=3)
                try:
                    shutil.copy2(path, _backup_path)
                except OSError:
                    # Backup is best-effort — never block the atomic write
                    pass

            os.replace(tmp, path)

            # Post-write verification: re-read and compare
            if verify:
                if not _post_write_verify(path, content):
                    raise AtomicWriteError(
                        f"Post-write verification failed for {path}: "
                        f"content mismatch after os.replace"
                    )
    except AtomicWriteError:
        raise
    except Exception:
        # Clean up the temp file on any failure so it doesn't linger
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise AtomicWriteError(
            f"Failed to atomically write {path}"
        ) from None

    emit(
        logger,
        "service.atomic_io.write",
        span_id="atomic_write",
        path=str(path),
        bytes_written=len(content),
        backup=backup,
        lock=lock,
        verify=verify,
        backup_rotation=backup_rotation,
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

    Conflict detection augments the inode/mtime/size snapshot with a
    SHA-256 content hash: the hash of the content read is captured and
    passed as ``expected_hash`` to ``atomic_write``, so a stale-overwrite
    is caught by *content equality* as well as by stat identity
    (ADR-005 Amendment 01, Augmentation 01).

    This eliminates the read-entire-file / modify-one-line /
    write-entire-file pattern that every service method currently
    replicates by hand (ADR-005 §4).
    """
    snapshot = _FileSnapshot(path)
    current = atomic_read(path)
    # SHA-256 of the content at load time — content-hash-based conflict
    # detection (Augmentation 01).  Omitted for a brand-new file.
    expected_hash = compute_content_hash(current) if current else None

    new_content = mutate(current)

    # Detect concurrent modification between read and write.
    if path.exists() and snapshot.mtime_ns is not None:
        if not snapshot.matches(path):
            raise ConcurrentWriteError(
                f"File {path} was modified concurrently during "
                f"read-modify-write; caller should retry."
            )

    atomic_write(path, new_content, backup=backup, expected_hash=expected_hash)


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
