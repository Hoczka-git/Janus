"""Targeted tests for Evidence Collection module.

Covers:
- Success case: full evidence with all fields
- Empty results: no changed files, no tests, no PR
- Partial results: some fields present, some missing
- Error cases: None input, malformed input
- Round-trip serialization (to_dict / from_dict)
- collect_safe with None and valid input
"""

from __future__ import annotations

import pytest

from janus.services.evidence_collection import (
    CommandOutput,
    Evidence,
    EvidenceCollector,
    EvidenceStatus,
    FileChange,
    LogEntry,
    StateSnapshot,
)
from janus.services.execution_feedback import (
    EvidencePackage,
    ExecutionResultMessage,
    JanusDomainMetadata,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def collector() -> EvidenceCollector:
    return EvidenceCollector()


@pytest.fixture
def full_metadata() -> JanusDomainMetadata:
    return JanusDomainMetadata(
        object="task",
        title="Implement feature X",
        changed_files=["src/foo.py", "tests/test_foo.py"],
        tests_passed=True,
        pr_url="https://github.com/example/repo/pull/42",
    )


@pytest.fixture
def full_evidence() -> EvidencePackage:
    return EvidencePackage(
        task_id="t_12345",
        summary="Implemented feature X with tests",
        changed_files=["src/foo.py", "tests/test_foo.py"],
        tests_passed=True,
        pr_url="https://github.com/example/repo/pull/42",
    )


@pytest.fixture
def full_result(
    full_metadata: JanusDomainMetadata, full_evidence: EvidencePackage
) -> ExecutionResultMessage:
    return ExecutionResultMessage(metadata=full_metadata, evidence=full_evidence)


@pytest.fixture
def empty_metadata() -> JanusDomainMetadata:
    return JanusDomainMetadata(object="task", title="Empty task")


@pytest.fixture
def empty_evidence() -> EvidencePackage:
    return EvidencePackage(task_id="t_empty", summary="")


@pytest.fixture
def empty_result(
    empty_metadata: JanusDomainMetadata, empty_evidence: EvidencePackage
) -> ExecutionResultMessage:
    return ExecutionResultMessage(metadata=empty_metadata, evidence=empty_evidence)


@pytest.fixture
def partial_metadata() -> JanusDomainMetadata:
    return JanusDomainMetadata(
        object="task",
        title="Partial task",
        changed_files=["src/bar.py"],
        tests_passed=None,
        pr_url=None,
    )


@pytest.fixture
def partial_evidence() -> EvidencePackage:
    return EvidencePackage(
        task_id="t_partial",
        summary="Partial implementation",
        changed_files=["src/bar.py"],
        tests_passed=None,
        pr_url=None,
    )


@pytest.fixture
def partial_result(
    partial_metadata: JanusDomainMetadata, partial_evidence: EvidencePackage
) -> ExecutionResultMessage:
    return ExecutionResultMessage(metadata=partial_metadata, evidence=partial_evidence)


# ── Success case ─────────────────────────────────────────────────────────────


class TestEvidenceCollectionSuccess:
    """Tests for successful evidence collection with full data."""

    def test_collect_returns_evidence(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert isinstance(result, Evidence)

    def test_collect_status_success(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert result.status == EvidenceStatus.SUCCESS

    def test_collect_task_id(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert result.task_id == "t_12345"

    def test_collect_domain_object(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert result.domain_object == "task"

    def test_collect_domain_title(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert result.domain_title == "Implement feature X"

    def test_collect_file_changes(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert len(result.file_changes) == 2
        assert result.file_changes[0].path == "src/foo.py"
        assert result.file_changes[1].path == "tests/test_foo.py"

    def test_collect_tests_passed(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert result.tests_passed is True

    def test_collect_pr_url(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert result.pr_url == "https://github.com/example/repo/pull/42"

    def test_collect_command_outputs(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert len(result.command_outputs) == 1
        assert result.command_outputs[0].command == "pytest"
        assert result.command_outputs[0].exit_code == 0

    def test_collect_logs(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert len(result.logs) == 1
        assert result.logs[0].source == "execution_feedback"
        assert "Implemented feature X" in result.logs[0].message

    def test_collect_state_snapshots(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert len(result.state_snapshots) == 1
        assert result.state_snapshots[0].label == "post-execution"
        assert "changed_files" in result.state_snapshots[0].state

    def test_collect_summary(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert "task" in result.summary
        assert "Implement feature X" in result.summary
        assert "2 file(s) changed" in result.summary
        assert "tests passed" in result.summary

    def test_collect_no_errors(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(full_result)
        assert result.errors == []


# ── Empty results ────────────────────────────────────────────────────────────


class TestEvidenceCollectionEmpty:
    """Tests for evidence collection with no data."""

    def test_collect_status_empty(
        self, collector: EvidenceCollector, empty_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(empty_result)
        assert result.status == EvidenceStatus.EMPTY

    def test_collect_no_file_changes(
        self, collector: EvidenceCollector, empty_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(empty_result)
        assert result.file_changes == []

    def test_collect_no_command_outputs(
        self, collector: EvidenceCollector, empty_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(empty_result)
        assert result.command_outputs == []

    def test_collect_no_logs(
        self, collector: EvidenceCollector, empty_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(empty_result)
        assert result.logs == []

    def test_collect_no_state_snapshots(
        self, collector: EvidenceCollector, empty_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(empty_result)
        assert result.state_snapshots == []

    def test_collect_tests_passed_none(
        self, collector: EvidenceCollector, empty_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(empty_result)
        assert result.tests_passed is None

    def test_collect_pr_url_none(
        self, collector: EvidenceCollector, empty_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(empty_result)
        assert result.pr_url is None


# ── Partial results ──────────────────────────────────────────────────────────


class TestEvidenceCollectionPartial:
    """Tests for evidence collection with partial data."""

    def test_collect_status_partial(
        self, collector: EvidenceCollector, partial_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(partial_result)
        assert result.status == EvidenceStatus.PARTIAL

    def test_collect_has_file_changes(
        self, collector: EvidenceCollector, partial_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(partial_result)
        assert len(result.file_changes) == 1
        assert result.file_changes[0].path == "src/bar.py"

    def test_collect_no_tests(
        self, collector: EvidenceCollector, partial_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(partial_result)
        assert result.tests_passed is None

    def test_collect_no_pr(
        self, collector: EvidenceCollector, partial_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(partial_result)
        assert result.pr_url is None

    def test_collect_no_command_outputs(
        self, collector: EvidenceCollector, partial_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(partial_result)
        assert result.command_outputs == []

    def test_collect_has_logs(
        self, collector: EvidenceCollector, partial_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(partial_result)
        assert len(result.logs) == 1

    def test_collect_has_state_snapshots(
        self, collector: EvidenceCollector, partial_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect(partial_result)
        assert len(result.state_snapshots) == 1


# ── Error cases ──────────────────────────────────────────────────────────────


class TestEvidenceCollectionErrors:
    """Tests for error handling in evidence collection."""

    def test_collect_safe_with_none(self, collector: EvidenceCollector) -> None:
        result = collector.collect_safe(None)
        assert result.status == EvidenceStatus.ERROR
        assert len(result.errors) == 1
        assert "No execution result" in result.errors[0]

    def test_collect_safe_with_valid_input(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect_safe(full_result)
        assert result.status == EvidenceStatus.SUCCESS

    def test_collect_safe_error_has_task_id_empty(
        self, collector: EvidenceCollector
    ) -> None:
        result = collector.collect_safe(None)
        assert result.task_id == ""

    def test_collect_safe_error_has_unknown_domain(
        self, collector: EvidenceCollector
    ) -> None:
        result = collector.collect_safe(None)
        assert result.domain_object == "unknown"
        assert result.domain_title == "unknown"


# ── Serialization round-trip ─────────────────────────────────────────────────


class TestEvidenceSerialization:
    """Tests for Evidence to_dict / from_dict round-trip."""

    def test_round_trip_full(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        original = collector.collect(full_result)
        data = original.to_dict()
        restored = Evidence.from_dict(data)
        assert restored.task_id == original.task_id
        assert restored.domain_object == original.domain_object
        assert restored.domain_title == original.domain_title
        assert restored.status == original.status
        assert restored.tests_passed == original.tests_passed
        assert restored.pr_url == original.pr_url
        assert len(restored.file_changes) == len(original.file_changes)
        assert len(restored.command_outputs) == len(original.command_outputs)
        assert len(restored.logs) == len(original.logs)
        assert len(restored.state_snapshots) == len(original.state_snapshots)

    def test_round_trip_empty(
        self, collector: EvidenceCollector, empty_result: ExecutionResultMessage
    ) -> None:
        original = collector.collect(empty_result)
        data = original.to_dict()
        restored = Evidence.from_dict(data)
        assert restored.status == EvidenceStatus.EMPTY
        assert restored.file_changes == []
        assert restored.command_outputs == []

    def test_from_dict_tolerates_missing_keys(self) -> None:
        data = {"task_id": "t_minimal"}
        evidence = Evidence.from_dict(data)
        assert evidence.task_id == "t_minimal"
        assert evidence.domain_object == ""
        assert evidence.status == EvidenceStatus.SUCCESS

    def test_to_dict_is_json_serializable(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        import json

        original = collector.collect(full_result)
        data = original.to_dict()
        json_str = json.dumps(data)
        assert isinstance(json_str, str)
        assert len(json_str) > 0


# ── Component model tests ────────────────────────────────────────────────────


class TestEvidenceComponents:
    """Tests for individual evidence component models."""

    def test_command_output_creation(self) -> None:
        co = CommandOutput(command="ls", stdout="file1\nfile2", exit_code=0)
        assert co.command == "ls"
        assert co.stdout == "file1\nfile2"
        assert co.exit_code == 0
        assert co.stderr == ""
        assert co.duration_ms is None

    def test_log_entry_creation(self) -> None:
        le = LogEntry(source="test", message="hello", level="INFO")
        assert le.source == "test"
        assert le.message == "hello"
        assert le.level == "INFO"
        assert le.timestamp is None

    def test_state_snapshot_creation(self) -> None:
        ss = StateSnapshot(label="pre-execution", state={"key": "value"})
        assert ss.label == "pre-execution"
        assert ss.state == {"key": "value"}
        assert ss.timestamp is None

    def test_file_change_creation(self) -> None:
        fc = FileChange(path="src/foo.py", change_type="modified")
        assert fc.path == "src/foo.py"
        assert fc.change_type == "modified"
        assert fc.diff is None

    def test_evidence_status_values(self) -> None:
        assert EvidenceStatus.SUCCESS == "success"
        assert EvidenceStatus.PARTIAL == "partial"
        assert EvidenceStatus.EMPTY == "empty"
        assert EvidenceStatus.ERROR == "error"


# ── Graceful degradation tests ───────────────────────────────────────────────


class TestGracefulDegradation:
    """Tests for graceful degradation with missing/partial inputs."""

    def test_collect_none_returns_error(self, collector: EvidenceCollector) -> None:
        result = collector.collect(None)
        assert result.status == EvidenceStatus.ERROR
        assert len(result.errors) == 1
        assert "No execution result" in result.errors[0]

    def test_collect_none_has_empty_task_id(
        self, collector: EvidenceCollector
    ) -> None:
        result = collector.collect(None)
        assert result.task_id == ""

    def test_collect_none_has_unknown_domain(
        self, collector: EvidenceCollector
    ) -> None:
        result = collector.collect(None)
        assert result.domain_object == "unknown"
        assert result.domain_title == "unknown"

    def test_collect_none_has_empty_file_changes(
        self, collector: EvidenceCollector
    ) -> None:
        result = collector.collect(None)
        assert result.file_changes == []

    def test_collect_none_has_empty_command_outputs(
        self, collector: EvidenceCollector
    ) -> None:
        result = collector.collect(None)
        assert result.command_outputs == []

    def test_collect_none_has_empty_logs(
        self, collector: EvidenceCollector
    ) -> None:
        result = collector.collect(None)
        assert result.logs == []

    def test_collect_none_has_empty_state_snapshots(
        self, collector: EvidenceCollector
    ) -> None:
        result = collector.collect(None)
        assert result.state_snapshots == []

    def test_collect_none_has_none_tests_passed(
        self, collector: EvidenceCollector
    ) -> None:
        result = collector.collect(None)
        assert result.tests_passed is None

    def test_collect_none_has_none_pr_url(
        self, collector: EvidenceCollector
    ) -> None:
        result = collector.collect(None)
        assert result.pr_url is None

    def test_collect_none_to_dict_json_serializable(
        self, collector: EvidenceCollector
    ) -> None:
        import json

        result = collector.collect(None)
        data = result.to_dict()
        json_str = json.dumps(data)
        assert isinstance(json_str, str)
        assert len(json_str) > 0

    def test_collect_none_round_trip(
        self, collector: EvidenceCollector
    ) -> None:
        original = collector.collect(None)
        data = original.to_dict()
        restored = Evidence.from_dict(data)
        assert restored.status == EvidenceStatus.ERROR
        assert restored.task_id == ""
        assert restored.domain_object == "unknown"

    def test_collect_with_none_metadata(
        self, collector: EvidenceCollector
    ) -> None:
        evidence_pkg = EvidencePackage(
            task_id="t_nometa",
            summary="test",
            changed_files=["src/foo.py"],
        )
        result_msg = ExecutionResultMessage(
            metadata=None,  # type: ignore[arg-type]
            evidence=evidence_pkg,
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        assert result.domain_object == "unknown"
        assert result.domain_title == "unknown"
        assert result.task_id == "t_nometa"

    def test_collect_with_none_evidence(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="task",
            title="Test task",
            changed_files=["src/bar.py"],
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata,
            evidence=None,  # type: ignore[arg-type]
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        assert result.domain_object == "task"
        assert result.domain_title == "Test task"
        assert result.task_id == ""

    def test_collect_with_both_none(
        self, collector: EvidenceCollector
    ) -> None:
        result_msg = ExecutionResultMessage(
            metadata=None,  # type: ignore[arg-type]
            evidence=None,  # type: ignore[arg-type]
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.EMPTY
        assert result.domain_object == "unknown"
        assert result.task_id == ""

    def test_collect_with_empty_changed_files(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="task",
            title="Empty files",
            changed_files=[],
        )
        evidence_pkg = EvidencePackage(
            task_id="t_empty_files",
            summary="No files changed",
            changed_files=[],
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.EMPTY
        assert result.file_changes == []

    def test_collect_with_empty_summary(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="task",
            title="No summary",
            changed_files=["src/foo.py"],
        )
        evidence_pkg = EvidencePackage(
            task_id="t_nosummary",
            summary="",
            changed_files=["src/foo.py"],
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        assert result.logs == []

    def test_collect_with_only_pr_url(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="task",
            title="PR only",
            pr_url="https://github.com/example/repo/pull/99",
        )
        evidence_pkg = EvidencePackage(
            task_id="t_pronly",
            summary="Only PR",
            pr_url="https://github.com/example/repo/pull/99",
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        assert result.pr_url == "https://github.com/example/repo/pull/99"
        assert result.file_changes == []

    def test_collect_with_only_body(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="research",
            title="Research artifact",
        )
        evidence_pkg = EvidencePackage(
            task_id="t_body",
            summary="Has body",
            body="# Research finding\n\nSome content",
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        assert result.domain_object == "research"

    def test_collect_with_only_janus_body(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="decision",
            title="ADR",
        )
        evidence_pkg = EvidencePackage(
            task_id="t_jbody",
            summary="Has janus_body",
            janus_body="# ADR-001\n\nDecision",
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        assert result.domain_object == "decision"

    def test_collect_with_tests_failed(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="task",
            title="Failing tests",
            changed_files=["src/foo.py"],
            tests_passed=False,
        )
        evidence_pkg = EvidencePackage(
            task_id="t_fail",
            summary="Tests failed",
            changed_files=["src/foo.py"],
            tests_passed=False,
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.SUCCESS
        assert result.tests_passed is False
        assert result.command_outputs[0].exit_code == 1

    def test_collect_with_changed_files_in_evidence_only(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="task",
            title="Files in evidence",
        )
        evidence_pkg = EvidencePackage(
            task_id="t_evfiles",
            summary="Files in evidence",
            changed_files=["src/from_evidence.py"],
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        assert len(result.file_changes) == 1
        assert result.file_changes[0].path == "src/from_evidence.py"

    def test_collect_with_changed_files_in_both(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="task",
            title="Files in both",
            changed_files=["src/from_metadata.py"],
        )
        evidence_pkg = EvidencePackage(
            task_id="t_both",
            summary="Files in both",
            changed_files=["src/from_evidence.py"],
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        # metadata.changed_files takes precedence (short-circuit or)
        assert len(result.file_changes) == 1
        assert result.file_changes[0].path == "src/from_metadata.py"

    def test_collect_safe_with_none_still_works(
        self, collector: EvidenceCollector
    ) -> None:
        result = collector.collect_safe(None)
        assert result.status == EvidenceStatus.ERROR

    def test_collect_safe_with_valid_still_works(
        self, collector: EvidenceCollector, full_result: ExecutionResultMessage
    ) -> None:
        result = collector.collect_safe(full_result)
        assert result.status == EvidenceStatus.SUCCESS

    def test_collect_with_special_characters_in_title(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="task",
            title="Task with 'quotes' and \"double quotes\" & <special>",
        )
        evidence_pkg = EvidencePackage(
            task_id="t_special",
            summary="Special chars",
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.EMPTY
        assert "quotes" in result.domain_title

    def test_collect_with_unicode_in_summary(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="task",
            title="Unicode task",
            changed_files=["src/unicode.py"],
        )
        evidence_pkg = EvidencePackage(
            task_id="t_unicode",
            summary="Zażółć gęślą jaźń 🎉",
            changed_files=["src/unicode.py"],
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        assert len(result.logs) == 1
        assert "Zażółć" in result.logs[0].message

    def test_collect_with_very_long_summary(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="task",
            title="Long summary",
            changed_files=["src/long.py"],
        )
        evidence_pkg = EvidencePackage(
            task_id="t_long",
            summary="x" * 10000,
            changed_files=["src/long.py"],
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        assert len(result.logs) == 1
        assert len(result.logs[0].message) == 10000

    def test_collect_with_many_changed_files(
        self, collector: EvidenceCollector
    ) -> None:
        files = [f"src/module_{i}.py" for i in range(100)]
        metadata = JanusDomainMetadata(
            object="task",
            title="Many files",
            changed_files=files,
        )
        evidence_pkg = EvidencePackage(
            task_id="t_many",
            summary="Many files",
            changed_files=files,
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        assert len(result.file_changes) == 100

    def test_collect_with_metric_updates(
        self, collector: EvidenceCollector
    ) -> None:
        metadata = JanusDomainMetadata(
            object="goal",
            title="Goal with metrics",
        )
        evidence_pkg = EvidencePackage(
            task_id="t_metrics",
            summary="Metric updates",
            metric_updates=[
                {"metric_name": "accuracy", "value": 0.95},
                {"metric_name": "loss", "value": 0.05},
            ],
        )
        result_msg = ExecutionResultMessage(
            metadata=metadata, evidence=evidence_pkg
        )
        result = collector.collect(result_msg)
        assert result.status == EvidenceStatus.PARTIAL
        assert result.domain_object == "goal"
