"""Unit tests for janus.integrations.atomic_io.

Covers:
- atomic_write: content correctness, no temp file leftovers, backup creation,
  parent directory creation, AtomicWriteError on failure.
- atomic_read: empty string for missing file, content round-trip.
- read_modify_write: mutate callback, ConcurrentWriteError on concurrent
  modification, atomicity of the full cycle.
- read_modify_write_with_retry: retry on ConcurrentWriteError, exhaustion
  after max_retries, success after transient conflict.

All tests use tmp_path for isolation and never touch real data/.
"""

import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from janus.integrations.atomic_io import (
    AtomicWriteError,
    ConcurrentWriteError,
    _FileSnapshot,
    atomic_read,
    atomic_write,
    read_modify_write,
    read_modify_write_with_retry,
)


# ── atomic_write ─────────────────────────────────────────────────────────────

class TestAtomicWrite:
    def test_writes_content_correctly(self, tmp_path):
        """Content written via atomic_write matches what was passed in."""
        fp = tmp_path / "out.txt"
        atomic_write(fp, "hello world")
        assert fp.read_text(encoding="utf-8") == "hello world"

    def test_no_temp_file_left_behind(self, tmp_path):
        """Temp file is cleaned up after a successful write."""
        fp = tmp_path / "out.txt"
        atomic_write(fp, "data")
        leftovers = list(tmp_path.glob("*.tmp.*"))
        assert leftovers == []

    def test_creates_parent_directories(self, tmp_path):
        """Parent directories are created if they don't exist."""
        fp = tmp_path / "nested" / "deep" / "out.txt"
        atomic_write(fp, "nested data")
        assert fp.read_text() == "nested data"

    def test_overwrites_existing_file(self, tmp_path):
        """atomic_write replaces an existing file's content atomically."""
        fp = tmp_path / "out.txt"
        fp.write_text("old content")
        atomic_write(fp, "new content")
        assert fp.read_text() == "new content"

    def test_backup_created_when_backup_true(self, tmp_path):
        """A .bak copy of the previous file is created when backup=True."""
        fp = tmp_path / "out.txt"
        fp.write_text("original")
        atomic_write(fp, "updated", backup=True)
        assert fp.read_text() == "updated"
        bak = tmp_path / "out.txt.bak"
        # backup goes to path.name + ".bak" in the same dir
        assert bak.exists()
        assert bak.read_text() == "original"

    def test_no_backup_when_backup_false(self, tmp_path):
        """No .bak file is created when backup=False."""
        fp = tmp_path / "out.txt"
        fp.write_text("original")
        atomic_write(fp, "updated", backup=False)
        assert fp.read_text() == "updated"
        assert not (tmp_path / "out.bak").exists()

    def test_backup_best_effort_on_failure(self, tmp_path):
        """Backup failure does not block the atomic write."""
        fp = tmp_path / "out.txt"
        fp.write_text("original")
        # Make backup fail by making the directory read-only for .bak creation
        # Actually, .bak is in the same dir; we patch shutil.copy2 to raise.
        with patch("shutil.copy2", side_effect=OSError("simulated backup failure")):
            atomic_write(fp, "updated", backup=True)
        assert fp.read_text() == "updated"

    def test_atomic_write_error_on_os_replace_failure(self, tmp_path):
        """AtomicWriteError is raised when the final replace fails."""
        fp = tmp_path / "out.txt"
        fp.write_text("original")
        with patch("os.replace", side_effect=OSError("simulated replace failure")):
            with pytest.raises(AtomicWriteError, match="Failed to atomically write"):
                atomic_write(fp, "data")
        # Original content is preserved because replace failed
        assert fp.read_text() == "original"

    @pytest.mark.parametrize("content", [
        "",
        "single line",
        "line1\nline2\nline3\n",
        "unicode: café ☕ €100",
    ])
    def test_various_content_types(self, tmp_path, content):
        """atomic_write handles empty strings, multiline, and unicode."""
        fp = tmp_path / "out.txt"
        atomic_write(fp, content)
        assert fp.read_text() == content


# ── atomic_read ──────────────────────────────────────────────────────────────

class TestAtomicRead:
    def test_returns_content(self, tmp_path):
        fp = tmp_path / "data.txt"
        fp.write_text("some content")
        assert atomic_read(fp) == "some content"

    def test_returns_empty_for_missing_file(self, tmp_path):
        """atomic_read returns empty string for a non-existent file."""
        fp = tmp_path / "nonexistent.txt"
        assert atomic_read(fp) == ""


# ── _FileSnapshot ──────────────────────────────────────────────────────────────

class TestFileSnapshot:
    def test_matches_identical_file(self, tmp_path):
        """A snapshot matches a file that hasn't changed."""
        fp = tmp_path / "f.txt"
        fp.write_text("content")
        snap = _FileSnapshot(fp)
        assert snap.matches(fp) is True

    def test_does_not_match_modified_file(self, tmp_path):
        """A snapshot doesn't match after the file is modified."""
        fp = tmp_path / "f.txt"
        fp.write_text("original")
        snap = _FileSnapshot(fp)
        # Force mtime change
        fp.write_text("modified")
        os.utime(fp, (datetime.now().timestamp() + 10, datetime.now().timestamp() + 10))
        assert snap.matches(fp) is False

    def test_snapshot_for_missing_file(self, tmp_path):
        """Snapshot of a non-existent file has None identity fields."""
        fp = tmp_path / "nonexistent.txt"
        snap = _FileSnapshot(fp)
        assert snap.mtime_ns is None
        assert snap.size is None
        assert snap.inode is None


# ── read_modify_write ────────────────────────────────────────────────────────

class TestReadWriteModifyWrite:
    def test_mutates_content(self, tmp_path):
        """The mutate callback's return value is written atomically."""
        fp = tmp_path / "state.txt"
        fp.write_text("hello")
        read_modify_write(fp, lambda current: current + " world")
        assert fp.read_text() == "hello world"

    def test_creates_new_file(self, tmp_path):
        """read_modify_write creates the file when it doesn't exist yet."""
        fp = tmp_path / "new.txt"
        assert not fp.exists()
        read_modify_write(fp, lambda current: "brand new")
        assert fp.read_text() == "brand new"

    def test_backup_created_on_modify(self, tmp_path):
        """A .bak of the pre-modify content exists when backup=True."""
        fp = tmp_path / "state.txt"
        fp.write_text("original content")
        read_modify_write(fp, lambda current: "modified content", backup=True)
        bak = tmp_path / "state.txt.bak"
        assert bak.exists()
        assert bak.read_text() == "original content"

    def test_concurrent_write_detected(self, tmp_path):
        """ConcurrentWriteError is raised if the file is modified between
        the read snapshot and the write phase."""
        fp = tmp_path / "state.txt"
        fp.write_text("original")

        def mutate(current):
            # Simulate a concurrent write during the mutate callback
            fp.write_text("concurrent modification")
            os.utime(fp, None)
            return current + " appended"

        with pytest.raises(ConcurrentWriteError, match="modified concurrently"):
            read_modify_write(fp, mutate)

        # The concurrent write wins — our append is NOT written
        assert fp.read_text() == "concurrent modification"

    def test_no_concurrent_write_when_file_new(self, tmp_path):
        """No ConcurrentWriteError when the file is created during the
        read-modify-write cycle (file didn't exist at snapshot time)."""
        fp = tmp_path / "new.txt"
        read_modify_write(fp, lambda current: "created", backup=True)
        assert fp.read_text() == "created"


# ── read_modify_write_with_retry ─────────────────────────────────────────────

class TestReadWriteModifyWriteWithRetry:
    def test_succeeds_without_conflict(self, tmp_path):
        """Happy path: no retry needed."""
        fp = tmp_path / "state.txt"
        fp.write_text("start")
        call_count = []

        def mutate(current):
            call_count.append(1)
            return current + "!"

        read_modify_write_with_retry(fp, mutate, max_retries=3, backoff_base=0.001)
        assert fp.read_text() == "start!"
        assert len(call_count) == 1

    def test_retries_on_concurrent_write(self, tmp_path):
        """read_modify_write_with_retry retries and eventually succeeds when
        a transient ConcurrentWriteError occurs."""
        fp = tmp_path / "state.txt"
        fp.write_text("start")
        attempts = []

        def mutate(current):
            attempts.append(current)
            if len(attempts) < 2:
                # Simulate concurrent write on first attempt
                fp.write_text("start")  # same content but new mtime
                os.utime(fp, None)
                return current + "!"
            return current + "!"

        # We need to make the first snapshot not match. The os.utime trick
        # in the mutate callback won't trigger ConcurrentWriteError because
        # the content is the same (mtime changes but the snapshot compares
        # mtime_ns, size, AND inode). os.utime changes mtime_ns.
        read_modify_write_with_retry(fp, mutate, max_retries=3, backoff_base=0.001)
        assert len(attempts) == 2

    def test_raises_after_max_retries(self, tmp_path):
        """ConcurrentWriteError propagates after max_retries exhausted."""
        fp = tmp_path / "state.txt"
        fp.write_text("start")

        def always_conflict(current):
            # Always modify the file to trigger ConcurrentWriteError
            fp.write_text("interference")
            os.utime(fp, None)
            return current + "!"

        with pytest.raises(ConcurrentWriteError):
            read_modify_write_with_retry(
                fp, always_conflict, max_retries=2, backoff_base=0.001
            )

    def test_backoff_uses_exponential(self, tmp_path):
        """Retry delays grow exponentially with attempt number."""
        fp = tmp_path / "state.txt"
        fp.write_text("start")
        delays = []

        def mutate(current):
            fp.write_text("interference")
            os.utime(fp, None)
            return current

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(ConcurrentWriteError):
                read_modify_write_with_retry(
                    fp, mutate, max_retries=3, backoff_base=0.1
                )
            # sleep called for retries 1, 2, 3
            assert mock_sleep.call_count == 3
            # Exponential: 0.1, 0.2, 0.4
            actual_delays = [call.args[0] for call in mock_sleep.call_args_list]
            assert actual_delays == [0.1, 0.2, 0.4]


# ── Integration: round-trip read-modify-write ────────────────────────────────

class TestAtomicIORoundTrip:
    def test_sequential_rmw_calls(self, tmp_path):
        """Multiple sequential read_modify_write calls produce correct
        cumulative state."""
        fp = tmp_path / "counter.txt"
        atomic_write(fp, "0")

        def increment(current):
            return str(int(current) + 1)

        read_modify_write(fp, increment)
        read_modify_write(fp, increment)
        read_modify_write(fp, increment)

        assert fp.read_text() == "3"

    def test_write_then_read_consistency(self, tmp_path):
        """Content written via atomic_write is immediately readable."""
        fp = tmp_path / "data.json"
        payload = '{"key": "value", "num": 42}'
        atomic_write(fp, payload)
        assert atomic_read(fp) == payload
