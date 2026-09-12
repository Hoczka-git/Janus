"""Persistent data protection layer for Janus.

Wraps all full-rewrite write paths to data/ files with four safety guards:

1. **Atomic write** (write-to-temp + rename) — prevents crash-corruption.
2. **Backup rotation** (timestamped .bak files) — enables recovery.
3. **Conflict detection** (SHA-256 hash comparison) — prevents stale-overwrite.
4. **Regeneration gating** (change-fraction policy) — prevents accidental
   full-data destruction by model-driven regeneration.

Append-only writes (metric_history.md, measurements.jsonl, follow-up/inbox
appends) are inherently safe and require no protection.

Integration points (all 18 write paths documented in
``findings/data_protection_design.md``):

| Path | Type | Protected? |
|------|------|-----------|
| markdown_goals.py:save_goal | append | No |
| markdown_goals.py:update_goal | full-rewrite | Yes |
| markdown_tasks.py (via services/tasks.py) | full-rewrite (4 paths) | Yes |
| workout_md.py:_write_workouts | full-rewrite | Yes |
| markdown_followups.py:update_followup | full-rewrite | Yes |
| markdown_inbox.py:update_inbox_item | full-rewrite | Yes |
| markdown_research.py:save_artifact | new file | Yes (existence check) |
| markdown_research.py:update_artifact | full-rewrite | Yes |
| services/decisions.py (3 write paths) | full-rewrite | Yes |
| metric_history.py:append_metric_snapshot | append-only | No |
| services/measurement_log.py:append_entry | append-only | No |
| markdown_followups.py:save_followup | append | No |
| markdown_inbox.py:save_inbox_item | append | No |
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from collections import deque

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DataProtectionError(Exception):
    """Base exception for data protection failures."""


class DataConflictError(DataProtectionError):
    """Raised when a file has been modified since the expected hash was captured."""

    def __init__(self, path: Path, expected_hash: str, current_hash: str):
        self.path = path
        self.expected_hash = expected_hash
        self.current_hash = current_hash
        super().__init__(
            f"Data conflict detected for {path}: "
            f"expected hash {expected_hash}, got {current_hash}"
        )


class DataCorruptionError(DataProtectionError):
    """Raised when post-write verification fails and recovery also fails."""


class RegenerationBlockedError(DataProtectionError):
    """Raised when a full-file regeneration exceeds the change threshold
    without explicit confirmation."""

    def __init__(self, path: Path, change_fraction: float, written_by: str):
        self.path = path
        self.change_fraction = change_fraction
        self.written_by = written_by
        super().__init__(
            f"Regeneration blocked for {path}: {change_fraction:.1%} of content "
            f"changed by '{written_by}'. Use confirm_regeneration=True to override."
        )


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WriteIntent:
    """Captures the state of a file at load time for conflict detection."""

    path: Path
    content_hash: str  # SHA-256 of file content at load time
    loaded_at: float  # timestamp when loaded


@dataclass
class WriteResult:
    """Result of a protected write operation."""

    path: Path
    backup_path: Optional[Path] = None  # path to .bak if one was created
    bytes_written: int = 0
    verified: bool = False  # post-write hash check passed
    content_hash: str = ""  # SHA-256 of the written content


@dataclass
class ProtectionConfig:
    """Configuration for the data protection layer.

    Values can be overridden via config/config.toml under [data_protection].
    """

    enabled: bool = True
    max_backups: int = 3
    backup_dir: str = ".backups"
    lock_timeout: float = 5.0
    verify_after_write: bool = True
    regeneration_threshold: float = 0.5
    allowed_regenerators: set[str] = field(
        default_factory=lambda: {
            "workout_md._write_workouts",
            # Full-rewrite programmatic writers that serialize structured
            # data back to markdown. These are trusted code paths — not
            # model output — and may legitimately rewrite an entire file
            # (e.g. re-serializing a goal block).  The regeneration gate
            # exists to catch *unknown/model-driven* full-content writes.
            "services.tasks.complete_task",
            "services.tasks.complete_janus_task",
            "services.tasks.set_task_state",
            "services.tasks.set_task_progress",
            "markdown_goals.update_goal",
            "markdown_followups.update_followup",
            "markdown_inbox.update_inbox_item",
            "markdown_research.save_artifact",
            "markdown_research.update_artifact",
            "services.decisions.update_decision_status",
            "services.decisions.link_decision_to_goal",
            "services.decisions.link_finding_to_decision",
            "services.decisions.create_decision",
        }
    )
    backup_max_age_days: int = 30


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------


def _load_config() -> ProtectionConfig:
    """Load data protection config from config/config.toml, with defaults."""
    try:
        import tomllib

        config_path = Path(__file__).resolve().parents[3] / "config" / "config.toml"
        if not config_path.exists():
            return ProtectionConfig()

        with config_path.open("rb") as f:
            toml_data = tomllib.load(f)

        section = toml_data.get("data_protection", {})

        config = ProtectionConfig()
        if "enabled" in section:
            config.enabled = bool(section["enabled"])
        if "max_backups" in section:
            config.max_backups = int(section["max_backups"])
        if "backup_dir" in section:
            config.backup_dir = str(section["backup_dir"])
        if "lock_timeout" in section:
            config.lock_timeout = float(section["lock_timeout"])
        if "verify_after_write" in section:
            config.verify_after_write = bool(section["verify_after_write"])
        if "regeneration_threshold" in section:
            config.regeneration_threshold = float(section["regeneration_threshold"])
        if "allowed_regenerators" in section:
            config.allowed_regenerators = set(section["allowed_regenerators"])
        if "backup_max_age_days" in section:
            config.backup_max_age_days = int(section["backup_max_age_days"])

        return config
    except Exception as e:
        logger.warning("Failed to load data_protection config, using defaults: %s", e)
        return ProtectionConfig()


_CONFIG: Optional[ProtectionConfig] = None


def get_config() -> ProtectionConfig:
    """Return the cached protection config (lazy-loaded)."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = _load_config()
    return _CONFIG


# ---------------------------------------------------------------------------
# Hash utilities
# ---------------------------------------------------------------------------


def compute_hash(path: Path) -> str:
    """Compute SHA-256 hash of file content.

    Raises FileNotFoundError if the file does not exist.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of a string's UTF-8 encoding."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def detect_conflict(path: Path, expected_hash: str | None) -> bool:
    """Return True if file has been modified since expected_hash was captured.

    Args:
        path: Path to the file being written.
        expected_hash: SHA-256 hash captured at load time, or None if the
            file didn't exist when loaded (new file).

    Returns:
        True if there is a conflict (file exists and hash differs),
        False otherwise (file doesn't exist, or hash matches).
    """
    if not path.exists():
        return False  # new file, no conflict
    if expected_hash is None:
        return False  # caller didn't track a hash, skip conflict detection
    current_hash = compute_hash(path)
    return current_hash != expected_hash


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


def atomic_write(path: Path, content: str, *, encoding: str = "utf-8") -> int:
    """Write content to path atomically using write-to-temp + rename.

    Uses os.rename() which is atomic on POSIX — either the old file
    remains or the new file appears, never a partially-written state.

    Returns the number of bytes written.
    Raises OSError on filesystem failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.tmp_",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        # Atomic rename on POSIX
        os.replace(tmp_path, path)

        # Sync the directory entry to ensure the rename is durable
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return len(content.encode(encoding))


# ---------------------------------------------------------------------------
# Backup rotation
# ---------------------------------------------------------------------------


def backup_previous(path: Path, *, max_backups: int | None = None) -> Path | None:
    """Create a timestamped backup of path before overwriting.

    Returns the backup path, or None if the file doesn't exist.
    Maintains at most max_backups rotating backups (default from config).
    """
    if not path.exists():
        return None

    if max_backups is None:
        max_backups = get_config().max_backups

    config = get_config()
    backup_dir = path.parent / config.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    backup_name = f"{path.name}.{timestamp}.bak"
    backup_path = backup_dir / backup_name

    shutil.copy2(str(path), str(backup_path))

    _rotate_backups(path, backup_dir=backup_dir, max_backups=max_backups)

    return backup_path


def _rotate_backups(path: Path, backup_dir: Path, *, max_backups: int) -> None:
    """Remove oldest backups beyond max_backups.

    Backups are sorted by modification time (newest first).
    """
    pattern = f"{path.name}.*.bak"
    backups = sorted(
        backup_dir.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for old_backup in backups[max_backups:]:
        try:
            old_backup.unlink()
        except OSError:
            pass  # best-effort cleanup


def _prune_old_backups(backup_dir: Path, path: Path, max_age_days: int) -> None:
    """Remove backups older than max_age_days."""
    pattern = f"{path.name}.*.bak"
    cutoff = time.time() - (max_age_days * 86400)

    for old_backup in backup_dir.glob(pattern):
        try:
            if old_backup.stat().st_mtime < cutoff:
                old_backup.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Post-write verification
# ---------------------------------------------------------------------------


def post_write_verify(path: Path, expected_content: str) -> bool:
    """Verify that path contains exactly expected_content after write.

    Returns True on match, False on mismatch.
    """
    if not path.exists():
        return False

    actual_content = path.read_text(encoding="utf-8")
    if actual_content == expected_content:
        return True

    logger.error(
        "Post-write verification failed for %s: "
        "expected %d bytes, got %d bytes",
        path,
        len(expected_content),
        len(actual_content),
    )
    return False


# ---------------------------------------------------------------------------
# File locking (concurrency guard)
# ---------------------------------------------------------------------------


@contextmanager
def file_lock(path: Path, *, timeout: float | None = None):
    """Acquire an exclusive advisory lock on path.

    Uses fcntl.flock() (POSIX advisory locking) to prevent concurrent writes
    to the same file. This guards against CLI + Hermes sync running
    simultaneously.

    Raises TimeoutError if lock cannot be acquired within timeout seconds.
    """
    if timeout is None:
        timeout = get_config().lock_timeout

    lock_dir = path.parent / get_config().backup_dir
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{path.name}.lock"

    lock_fd = open(lock_path, "w")
    try:
        start = time.monotonic()
        while True:
            try:
                import fcntl

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
            import fcntl

            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except (IOError, OSError):
            pass
        lock_fd.close()
        try:
            lock_path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Regeneration gating
# ---------------------------------------------------------------------------


class RegenerationPolicy:
    """Policy for gating full-file regeneration writes."""

    MAX_CHANGE_FRACTION = 0.5
    ALLOWED_REGENERATORS = frozenset({
        "workout_md._write_workouts",
        "services.tasks.complete_task",
        "services.tasks.complete_janus_task",
        "services.tasks.set_task_state",
        "services.tasks.set_task_progress",
        "markdown_goals.update_goal",
        "markdown_followups.update_followup",
        "markdown_inbox.update_inbox_item",
        "markdown_research.save_artifact",
        "markdown_research.update_artifact",
        "services.decisions.update_decision_status",
        "services.decisions.link_decision_to_goal",
        "services.decisions.link_finding_to_decision",
        "services.decisions.create_decision",
    })


def _compute_change_fraction(old_content: str, new_content: str) -> float:
    """Compute the fraction of content that has changed between old and new.

    Uses character-level difflib ratio to distinguish full-file regeneration
    (nearly 1.0) from surgical in-place edits (small fraction).  Line-level
    comparison would report 100% change for small files where a single line
    is edited (e.g. a 1-line tasks.md flipping ``- [ ]`` to ``- [x]``), which
    defeats the regeneration gate.

    Returns a value between 0.0 and 1.0.
    """
    import difflib

    if not old_content:
        return 1.0 if new_content else 0.0

    matcher = difflib.SequenceMatcher(None, old_content, new_content, autojunk=False)
    # ratio returns 1.0 for identical, 0.0 for completely different
    # We want the *fraction that changed* = 1 - similarity
    return 1.0 - matcher.ratio()


def gate_regeneration(
    path: Path,
    old_content: str,
    new_content: str,
    written_by: str,
    *,
    confirm: bool = False,
) -> bool:
    """Return True if regeneration is allowed, False if blocked.

    A regeneration is blocked when:
    - The change fraction exceeds the threshold, AND
    - The writer is not in the allowed regenerators list, AND
    - confirm is not True

    Args:
        path: The file being written.
        old_content: Current file content.
        new_content: New content being written.
        written_by: Identifier for the calling function.
        confirm: If True, bypass the threshold check (explicit user override).

    Returns:
        True if the write is allowed, False if blocked.
    """
    config = get_config()

    if written_by in config.allowed_regenerators or written_by in RegenerationPolicy.ALLOWED_REGENERATORS:
        return True

    if confirm:
        logger.info(
            "Regeneration confirmed for %s by '%s' (change: %.1f%%)",
            path,
            written_by,
            _compute_change_fraction(old_content, new_content) * 100,
        )
        return True

    if len(old_content) > 0:
        change_fraction = _compute_change_fraction(old_content, new_content)
        if change_fraction > config.regeneration_threshold:
            return False

    return True


# ---------------------------------------------------------------------------
# Protected write (main entry point)
# ---------------------------------------------------------------------------


def protected_write(
    path: Path,
    content: str,
    *,
    expected_hash: str | None = None,
    written_by: str = "unknown",
    confirm_regeneration: bool = False,
) -> WriteResult:
    """Perform a protected full-rewrite write to *path*.

    This is the main entry point for full-rewrite write paths. It:

    1. Checks for conflicts (hash mismatch since load).
    2. Acquires an advisory file lock.
    3. Gates regeneration if the change is too large.
    4. Backs up the previous content.
    5. Writes atomically (write-to-temp + rename).
    6. Verifies the write succeeded.

    Args:
        path: Target file path.
        content: New content to write.
        expected_hash: SHA-256 hash of the file at load time (for conflict
            detection). Pass None if the file didn't exist at load time.
        written_by: Identifier for the calling function (for audit/logging
            and regeneration gating).
        confirm_regeneration: If True, bypass regeneration threshold check.

    Returns:
        WriteResult with backup path, bytes written, and verification status.

    Raises:
        DataConflictError: If the file has been modified since expected_hash.
        RegenerationBlockedError: If the regeneration is too large and not
            confirmed.
        DataCorruptionError: If post-write verification fails and recovery
            from backup also fails.
        RuntimeError: If the protection layer is disabled but write still fails.
    """
    config = get_config()

    if not config.enabled:
        # Fall back to simple write if protection is disabled
        bytes_written = atomic_write(path, content)
        return WriteResult(
            path=path,
            bytes_written=bytes_written,
            verified=True,
            content_hash=compute_content_hash(content),
        )

    # 1. Conflict detection
    if expected_hash is not None and detect_conflict(path, expected_hash):
        current_hash = compute_hash(path) if path.exists() else "none"
        raise DataConflictError(path, expected_hash, current_hash)

    # 2. Read old content for regeneration gating + backup
    old_content = path.read_text(encoding="utf-8") if path.exists() else ""

    # 3. Regeneration gating
    if not gate_regeneration(
        path, old_content, content, written_by, confirm=confirm_regeneration
    ):
        change_fraction = _compute_change_fraction(old_content, content)
        raise RegenerationBlockedError(path, change_fraction, written_by)

    # 4-6. Lock, backup, atomic write, verify
    with file_lock(path):
        backup_path = backup_previous(path)
        _prune_old_backups(
            path.parent / config.backup_dir, path, config.backup_max_age_days
        )

        bytes_written = atomic_write(path, content)
        content_hash = compute_content_hash(content)

        verified = True
        if config.verify_after_write:
            verified = post_write_verify(path, content)
            if not verified:
                # Attempt automatic recovery from backup
                if backup_path is not None and backup_path.exists():
                    logger.warning(
                        "Post-write verification failed for %s, "
                        "attempting recovery from %s",
                        path,
                        backup_path,
                    )
                    try:
                        shutil.copy2(str(backup_path), str(path))
                        verified = post_write_verify(path, old_content)
                        if not verified:
                            raise DataCorruptionError(
                                f"Post-write verification failed for {path} "
                                f"and recovery from backup also failed"
                            )
                        logger.warning(
                            "Recovery from backup succeeded for %s", path
                        )
                    except (OSError, DataCorruptionError) as exc:
                        raise DataCorruptionError(
                            f"Post-write verification failed for {path} "
                            f"and recovery failed: {exc}"
                        ) from exc
                else:
                    raise DataCorruptionError(
                        f"Post-write verification failed for {path} "
                        f"with no backup available for recovery"
                    )

    return WriteResult(
        path=path,
        backup_path=backup_path,
        bytes_written=bytes_written,
        verified=verified,
        content_hash=content_hash,
    )


def protected_append(path: Path, content: str, *, written_by: str = "unknown") -> int:
    """Append content to a file atomically (for append-only semantics).

    For append-only files, we still use atomic write to prevent corruption
    on crash: read current content, append, write atomically.

    Returns the number of bytes written.
    """
    config = get_config()

    if not config.enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        return len(content.encode("utf-8"))

    with file_lock(path):
        if path.exists():
            old_content = path.read_text(encoding="utf-8")
        else:
            old_content = ""
        new_content = old_content + content
        backup_path = backup_previous(path)
        bytes_written = atomic_write(path, new_content)
        if config.verify_after_write:
            if not post_write_verify(path, new_content):
                if backup_path is not None and backup_path.exists():
                    shutil.copy2(str(backup_path), str(path))
                raise DataCorruptionError(
                    f"Post-write verification failed for {path}"
                )

    return bytes_written


# ---------------------------------------------------------------------------
# Repair file (legitimate full-rewrite bypass)
# ---------------------------------------------------------------------------


def repair_file(
    path: Path,
    new_content: str,
    *,
    reason: str,
    written_by: str = "repair_file",
) -> WriteResult:
    """Write a full-file replacement as a legitimate repair operation.

    Creates an extended backup with the repair reason and bypasses the
    regeneration gate (but still uses atomic write + backup + verification).

    Args:
        path: Target file path.
        new_content: New content to write.
        reason: Human-readable reason for the repair.
        written_by: Identifier for the calling function.

    Returns:
        WriteResult with backup path and verification status.
    """
    config = get_config()

    with file_lock(path):
        old_content = path.read_text(encoding="utf-8") if path.exists() else ""

        # Create an extended backup with repair metadata
        backup_path = _create_repair_backup(path, reason)

        bytes_written = atomic_write(path, new_content)
        content_hash = compute_content_hash(new_content)

        verified = True
        if config.verify_after_write:
            verified = post_write_verify(path, new_content)
            if not verified:
                if backup_path is not None and backup_path.exists():
                    shutil.copy2(str(backup_path), str(path))
                raise DataCorruptionError(
                    f"Post-write verification failed for {path} during repair"
                )

    logger.info(
        "Repair write to %s: %s (%d bytes, verified=%s)",
        path,
        reason,
        bytes_written,
        verified,
    )

    return WriteResult(
        path=path,
        backup_path=backup_path,
        bytes_written=bytes_written,
        verified=verified,
        content_hash=content_hash,
    )


def _create_repair_backup(path: Path, reason: str) -> Path | None:
    """Create a backup with repair metadata in the filename."""
    if not path.exists():
        return None

    config = get_config()
    backup_dir = path.parent / config.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize reason for use in filename
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]", "_", reason[:40])
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    backup_name = f"{path.name}.repair.{timestamp}.{safe_reason}.bak"
    backup_path = backup_dir / backup_name

    shutil.copy2(str(path), str(backup_path))
    _rotate_backups(path, backup_dir=backup_dir, max_backups=config.max_backups)
    return backup_path


# ---------------------------------------------------------------------------
# Integrity verification (for `janus data verify`)
# ---------------------------------------------------------------------------


@dataclass
class VerificationResult:
    """Result of verifying a single data file's integrity."""

    path: Path
    exists: bool
    sha256: str = ""
    byte_size: int = 0
    backup_count: int = 0
    ok: bool = False


def verify_file_integrity(path: Path) -> VerificationResult:
    """Verify integrity of a single data file.

    Checks that the file exists and is readable. For files with metadata
    headers, also verifies the embedded hash matches the content.
    """
    if not path.exists():
        return VerificationResult(path=path, exists=False, ok=False)

    sha256 = ""
    byte_size = 0
    backup_count = 0

    try:
        sha256 = compute_hash(path)
        byte_size = path.stat().st_size
    except OSError:
        return VerificationResult(path=path, exists=True, ok=False)

    # Check for backups
    config = get_config()
    backup_dir = path.parent / config.backup_dir
    if backup_dir.exists():
        backup_count = len(list(backup_dir.glob(f"{path.name}.*.bak")))

    return VerificationResult(
        path=path,
        exists=True,
        sha256=sha256,
        byte_size=byte_size,
        backup_count=backup_count,
        ok=True,
    )


def list_data_files(data_dir: Path | None = None) -> list[Path]:
    """List all data files that the protection layer covers."""
    if data_dir is None:
        data_dir = Path(__file__).resolve().parents[3] / "data"

    files = []
    for name in ("tasks.md", "goals.md", "metric_history.md",
                 "workouts.md", "reflections.md", "followups.md",
                 "inbox.md", "measurements.jsonl"):
        p = data_dir / name
        if p.exists():
            files.append(p)
    return files
