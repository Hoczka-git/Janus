"""Backward-compatibility shim for the legacy ``data_protection`` API.

.. deprecated::
    The data-protection policy layer has been folded into:

    * ``atomic_io`` (write primitives + SHA-256 conflict detection),
    * ``data_integrity`` (backup rotation, locking, post-write verification,
      ``repair_file`` / ``verify_file_integrity``),
    * ``activity_ingest`` (regeneration gating).

    This module re-exports the public surface from its new homes so that
    existing callers and tests continue to import from the legacy path during
    the deprecation window.  It will be removed once the remaining in-repo
    callers have migrated (see ADR-005 Amendment 01, Migration Path).
"""
from __future__ import annotations

import warnings as _warnings

from janus.integrations.atomic_io import (
    AtomicWriteError,
    ConcurrentWriteError,
    HashConflictError,
    atomic_read,
    atomic_write,
    compute_content_hash,
    compute_file_hash,
    detect_hash_conflict,
    read_modify_write,
    read_modify_write_with_retry,
)
from janus.integrations.data_integrity import (
    BACKUP_DIR,
    CONFIG_PATH,
    DATA_DIR,
    DataConflictError,
    DataCorruptionError,
    DataProtectionError,
    ProtectionConfig,
    RegenerationBlockedError,
    RegenerationPolicy,
    VerificationResult,
    WriteIntent,
    WriteResult,
    _compute_change_fraction,
    _create_repair_backup,
    backup_previous,
    compute_hash,
    detect_conflict,
    file_lock,
    gate_regeneration,
    get_config,
    get_data_dir,
    list_data_files,
    post_write_verify,
    protected_append,
    protected_write,
    repair_file,
    verify_data_dir,
    verify_file_integrity,
)

__all__ = [
    # atomic_io primitives
    "AtomicWriteError",
    "ConcurrentWriteError",
    "HashConflictError",
    "atomic_read",
    "atomic_write",
    "compute_content_hash",
    "compute_file_hash",
    "detect_hash_conflict",
    "read_modify_write",
    "read_modify_write_with_retry",
    # data_integrity
    "DataProtectionError",
    "DataConflictError",
    "DataCorruptionError",
    "RegenerationBlockedError",
    "WriteIntent",
    "WriteResult",
    "ProtectionConfig",
    "RegenerationPolicy",
    "VerificationResult",
    "get_config",
    "compute_hash",
    "compute_content_hash",
    "detect_conflict",
    "backup_previous",
    "file_lock",
    "post_write_verify",
    "gate_regeneration",
    "protected_write",
    "protected_append",
    "repair_file",
    "verify_file_integrity",
    "list_data_files",
    "verify_data_dir",
    "BACKUP_DIR",
    "CONFIG_PATH",
    "DATA_DIR",
    "get_data_dir",
    "_compute_change_fraction",
]

_warnings.warn(
    "janus.integrations.data_protection is deprecated; import from "
    "janus.integrations.atomic_io, janus.integrations.data_integrity or "
    "janus.services.activity_ingest instead.",
    DeprecationWarning,
    stacklevel=2,
)
