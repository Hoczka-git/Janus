"""Targeted tests for the data integrity / protection layer.

Tests cover the four safety guards from the original data_protection spec:
  1. Existence checks before writes (new-file guard)
  2. Conflict detection (stale-load hash -> DataConflictError)
  3. Regeneration gating (excessive change by untrusted writer -> RegenerationBlockedError)
  4. Atomic write + backup rotation + post-write verification

These tests now import from the canonical homes:
  - ``janus.integrations.data_integrity`` (protected_write, protected_append,
    backup_previous, detect_conflict, gate_regeneration, repair_file,
    verify_file_integrity, and config/data classes)
  - ``janus.integrations.atomic_io`` (compute_content_hash)

The legacy ``data_protection.py`` shim was removed once all writers migrated
to atomic_io (ADR-005 Amendment 01 deprecation criteria). See
``docs/decisions/005-01-atomic_io-vs-data_protection-amendment.md``.
"""
from __future__ import annotations

import os
import pathlib

import pytest

from janus.integrations.atomic_io import compute_content_hash
from janus.integrations.data_integrity import (
    DataConflictError,
    DataCorruptionError,
    RegenerationBlockedError,
    ProtectionConfig,
    WriteResult,
    backup_previous,
    compute_hash,
    detect_conflict,
    gate_regeneration,
    get_config,
    protected_append,
    protected_write,
    repair_file,
    verify_file_integrity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_tmp_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


def _seed_file(path: pathlib.Path, content: str) -> str:
    """Write a seeded file and return its content hash (simulating load-time capture)."""
    path.write_text(content)
    return compute_content_hash(content)


# ---------------------------------------------------------------------------
# 1. Existence check / new-file guard (save_artifact pattern)
# ---------------------------------------------------------------------------
class TestNewFileWriterGuard:
    """save_artifact uses expected_hash=None for new files — write always succeeds."""

    def test_new_file_write_succeeds(self, tmp_path):
        path = _make_tmp_dir(tmp_path) / "artifact.md"
        result = protected_write(
            path, "# New artifact\n",
            expected_hash=None,
            written_by="test.writer",
        )
        assert result.verified
        assert path.read_text() == "# New artifact\n"


# ---------------------------------------------------------------------------
# 2. Conflict detection (stale-load hash -> DataConflictError)
# ---------------------------------------------------------------------------
class TestConflictDetection:
    """If a file is modified since the expected hash was captured, the write
    is refused with DataConflictError — preserving the current file."""

    def test_conflict_raises_and_preserves_file(self, tmp_path):
        path = _make_tmp_dir(tmp_path) / "tasks.md"
        original = "# Tasks\n\n- [ ] Buy shoes\n"
        expected_hash = _seed_file(path, original)

        # Simulate another process modifying the file after we loaded it
        path.write_text(original + "- [ ] Another task\n")

        with pytest.raises(DataConflictError):
            protected_write(
                path,
                "# Tasks\n\n- [x] Buy shoes\n",
                expected_hash=expected_hash,
                written_by="test.writer",
            )

        # The file is preserved — the conflicting write did NOT land
        assert path.read_text() == original + "- [ ] Another task\n"

    def test_no_conflict_when_hash_matches(self, tmp_path):
        path = _make_tmp_dir(tmp_path) / "goals.md"
        original = "# Goals\n\n## Goal: G\nStatus: active\n"
        expected_hash = _seed_file(path, original)

        # Same content, different formatting — hash matches so no conflict
        result = protected_write(
            path,
            original,  # identical content
            expected_hash=expected_hash,
            written_by="test.writer",
        )
        assert result.verified

    def test_no_conflict_for_new_file(self, tmp_path):
        path = _make_tmp_dir(tmp_path) / "new.md"
        # File doesn't exist, expected_hash=None -> no conflict
        result = protected_write(
            path, "fresh\n",
            expected_hash=None,
            written_by="test.writer",
        )
        assert result.verified


# ---------------------------------------------------------------------------
# 3. Regeneration gating
# ---------------------------------------------------------------------------
class TestRegenerationGate:
    """A full-content regeneration by an untrusted writer that exceeds the
    threshold is blocked — the file is preserved."""

    def test_untrusted_writer_blocked_on_massive_change(self, tmp_path):
        path = _make_tmp_dir(tmp_path) / "workouts.md"
        original = "# Workouts\n\n2026-01-01: 30 min run\n"
        _seed_file(path, original)

        with pytest.raises(RegenerationBlockedError):
            protected_write(
                path,
                "# Workouts\n\n" + "x" * 5000 + "\n",
                expected_hash=compute_content_hash(original),
                written_by="model.regeneration",  # not in allowed_regenerators
            )

        # File is preserved unchanged
        assert path.read_text() == original

    def test_allowed_writer_bypasses_gate(self, tmp_path):
        """Known programmatic writers are whitelisted and may rewrite."""
        path = _make_tmp_dir(tmp_path) / "tasks.md"
        original = "- [ ] Buy shoes\n"
        expected_hash = _seed_file(path, original)

        # A near-total rewrite by an allowed writer still succeeds
        result = protected_write(
            path,
            "- [x] Buy shoes | janus_evidence_task_id: t_123\n",
            expected_hash=expected_hash,
            written_by="services.tasks.complete_janus_task",
        )
        assert result.verified
        assert "- [x]" in path.read_text()

    def test_confirm_override_bypasses_gate(self, tmp_path):
        """confirm_regeneration=True bypasses the threshold for one-off repairs."""
        path = _make_tmp_dir(tmp_path) / "goals.md"
        original = "# Goals\n\n## Goal: G\nStatus: active\n"
        expected_hash = _seed_file(path, original)

        result = protected_write(
            path,
            "# Goals\n\n## Goal: G\nStatus: active\nDescription: totally rewritten content\n",
            expected_hash=expected_hash,
            written_by="test.writer",
            confirm_regeneration=True,
        )
        assert result.verified

    def test_small_edit_by_unknown_writer_allowed(self, tmp_path):
        """A surgical edit (small change fraction) by an unknown writer is
        allowed — the gate only blocks massive changes."""
        path = _make_tmp_dir(tmp_path) / "tasks.md"
        original = "- [ ] Buy running shoes | due: 2026-09-04 | priority: 1\n"
        expected_hash = _seed_file(path, original)

        result = protected_write(
            path,
            "- [x] Buy running shoes | due: 2026-09-04 | priority: 1\n",
            expected_hash=expected_hash,
            written_by="unknown.cli",
        )
        assert result.verified
        assert "- [x]" in path.read_text()


# ---------------------------------------------------------------------------
# 4. Atomic write + backup rotation + post-write verification
# ---------------------------------------------------------------------------
class TestAtomicWriteAndBackups:
    """protected_write creates a backup before overwriting and rotates old backups."""

    def test_backup_created_on_overwrite(self, tmp_path):
        path = _make_tmp_dir(tmp_path) / "data.md"
        original = "original content\n"
        _seed_file(path, original)

        # Bypass regeneration gate via confirm for this test
        protected_write(
            path, "new content\n",
            expected_hash=compute_content_hash(original),
            written_by="test.writer",
            confirm_regeneration=True,
        )

        backup_dir = path.parent / get_config().backup_dir
        backups = sorted(backup_dir.glob("data.md.*.bak"))
        assert len(backups) >= 1
        assert backups[-1].read_text() == "original content\n"

    def test_backup_rotation_enforces_max(self, tmp_path):
        path = _make_tmp_dir(tmp_path) / "rot.md"
        _seed_file(path, "v0\n")

        for i in range(1, 10):
            protected_write(
                path, f"v{i}\n",
                expected_hash=compute_content_hash(f"v{i-1}\n"),
                written_by="test.writer",
                confirm_regeneration=True,
            )

        backup_dir = path.parent / get_config().backup_dir
        backups = list(backup_dir.glob("rot.md.*.bak"))
        assert len(backups) <= get_config().max_backups

    def test_post_write_verification_confirms_content(self, tmp_path):
        path = _make_tmp_dir(tmp_path) / "verify.md"
        result = protected_write(
            path, "hello world\n",
            expected_hash=None,
            written_by="test.writer",
        )
        assert result.verified
        assert result.content_hash == compute_content_hash("hello world\n")
        assert result.bytes_written == len("hello world\n".encode("utf-8"))


# ---------------------------------------------------------------------------
# 5. Existence check before writes (seeded file preservation)
# ---------------------------------------------------------------------------
class TestSeededFilePreservation:
    """Core task scenario: a seeded data/ file cannot be silently overwritten
    by a conflicting write — it is either preserved or handled per design."""

    def test_seeded_file_preserved_on_conflict(self, tmp_path):
        """A concurrent modification between load and write is detected and
        the seeded file is preserved (not silently overwritten)."""
        path = _make_tmp_dir(tmp_path) / "seeded.md"
        seed = "seeded content that must be preserved\n"
        load_hash = _seed_file(path, seed)

        # Adversary modifies the file
        path.write_text("adversary overwrite\n")

        with pytest.raises(DataConflictError):
            protected_write(
                path,
                "model output content\n",
                expected_hash=load_hash,
                written_by="model.output",
            )

        assert path.read_text() == "adversary overwrite\n"

    def test_seeded_file_preserved_on_regeneration_block(self, tmp_path):
        """A model-driven full regeneration is blocked — the seeded file
        is preserved unchanged."""
        path = _make_tmp_dir(tmp_path) / "seeded.md"
        seed = "legitimate seeded data\n" * 5
        load_hash = _seed_file(path, seed)

        with pytest.raises(RegenerationBlockedError):
            protected_write(
                path,
                "completely different model-generated content\n" * 20,
                expected_hash=load_hash,
                written_by="model.regeneration",
            )

        assert path.read_text() == seed


# ---------------------------------------------------------------------------
# 6. Utility functions
# ---------------------------------------------------------------------------
class TestUtilities:
    def test_compute_hash_matches_content_hash(self, tmp_path):
        path = tmp_path / "f.txt"
        path.write_text("hello")
        assert compute_hash(path) == compute_content_hash("hello")

    def test_detect_conflict_no_file(self, tmp_path):
        path = tmp_path / "nonexistent"
        assert detect_conflict(path, "abc") is False

    def test_detect_conflict_no_expected_hash(self, tmp_path):
        path = tmp_path / "f.txt"
        path.write_text("content")
        assert detect_conflict(path, None) is False

    def test_detect_conflict_mismatch(self, tmp_path):
        path = tmp_path / "f.txt"
        path.write_text("content")
        assert detect_conflict(path, "wrong_hash") is True

    def test_detect_conflict_match(self, tmp_path):
        path = tmp_path / "f.txt"
        path.write_text("content")
        h = compute_content_hash("content")
        assert detect_conflict(path, h) is False

    def test_verify_file_integrity_existing(self, tmp_path):
        path = tmp_path / "f.txt"
        path.write_text("content")
        result = verify_file_integrity(path)
        assert result.exists
        assert result.ok
        assert result.sha256 == compute_hash(path)

    def test_verify_file_integrity_missing(self, tmp_path):
        path = tmp_path / "missing"
        result = verify_file_integrity(path)
        assert not result.exists
        assert not result.ok


# ---------------------------------------------------------------------------
# 7. protected_append — migrated from raw open("a") to atomic_io
# ---------------------------------------------------------------------------
class TestProtectedAppend:
    """Tests for ``protected_append`` in ``data_integrity``.

    The config-disabled path previously bypassed ``atomic_io`` with a raw
    ``open("a")`` call (audit §1.7 / §4 known gate bypasses). It now routes
    through ``atomic_io`` (via ``read_modify_write`` / ``atomic_write``)
    unconditionally.
    """

    def test_append_to_new_file_creates_file(self, tmp_path, monkeypatch):
        """Appending to a non-existent file creates it with the content."""
        monkeypatch.setattr(
            "janus.integrations.data_integrity.get_config",
            lambda: ProtectionConfig(enabled=True),
        )
        path = _make_tmp_dir(tmp_path) / "append_new.md"
        bytes_written = protected_append(path, "first line\n")
        assert path.exists()
        assert path.read_text() == "first line\n"
        assert bytes_written == len("first line\n".encode("utf-8"))

    def test_append_to_existing_file(self, tmp_path, monkeypatch):
        """Appending to an existing file preserves old content and appends new."""
        monkeypatch.setattr(
            "janus.integrations.data_integrity.get_config",
            lambda: ProtectionConfig(enabled=True),
        )
        path = _make_tmp_dir(tmp_path) / "append_existing.md"
        path.write_text("old content\n")
        protected_append(path, "new content\n")
        assert path.read_text() == "old content\nnew content\n"

    def test_config_disabled_uses_atomic_io(self, tmp_path, monkeypatch):
        """When protection is disabled, the append still routes through
        atomic_io — no raw ``open("a")`` bypass (audit §1.7/§4)."""
        monkeypatch.setattr(
            "janus.integrations.data_integrity.get_config",
            lambda: ProtectionConfig(enabled=False),
        )
        path = _make_tmp_dir(tmp_path) / "append_disabled.md"
        path.write_text("seeded\n")
        protected_append(path, "appended\n")
        assert path.read_text() == "seeded\nappended\n"

    def test_config_disabled_creates_new_file(self, tmp_path, monkeypatch):
        """Config-disabled append on a non-existent file creates it safely."""
        monkeypatch.setattr(
            "janus.integrations.data_integrity.get_config",
            lambda: ProtectionConfig(enabled=False),
        )
        path = _make_tmp_dir(tmp_path) / "append_disabled_new.md"
        protected_append(path, "brand new\n")
        assert path.read_text() == "brand new\n"

    def test_config_disabled_preserves_existing_no_loss(self, tmp_path, monkeypatch):
        """Regression guard: the config-disabled path must not lose content
        by opening in append mode and racing. The read-then-write-via-atomic
        approach guarantees the full existing content is preserved."""
        monkeypatch.setattr(
            "janus.integrations.data_integrity.get_config",
            lambda: ProtectionConfig(enabled=False),
        )
        path = _make_tmp_dir(tmp_path) / "append_preserve.md"
        # Seed with multi-line content
        path.write_text("line1\nline2\nline3\n")
        protected_append(path, "line4\n")
        content = path.read_text()
        assert content == "line1\nline2\nline3\nline4\n"
        assert "line1" in content and "line4" in content
