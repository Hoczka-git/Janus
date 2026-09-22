# Goal Integrity Audit — Test Requirements

Source spec: `docs/design/goal_integrity_audit.md` §12 (Testing).

This document records the 12 required test cases for the Goal Integrity Audit
feature, extracted from the design spec by scanning `docs/design/goal_integrity_audit.md`.

## Issue codes covered

| Code                     | Severity  | Trigger                                                         |
|--------------------------|-----------|-----------------------------------------------------------------|
| `GOAL_WITHOUT_TASKS`     | warning   | Active goal has no related open/actionable tasks.               |
| `UNKNOWN_GOAL_REFERENCE` | error     | A task references a goal ID that does not exist.                |
| `INVALID_METRIC`         | error     | A goal has incomplete or inconsistent metric configuration.     |
| `STALE_ACTIVITY`         | warning   | An active goal has no relevant activity within the freshness window. |

## Required test cases

| #  | Area               | Spec §12 | Description                                                  |
|----|--------------------|----------|--------------------------------------------------------------|
| 1  | service            | §12(1)   | Healthy goals/tasks: no issues for valid metric/task goals.  |
| 2  | service            | §12(2)   | Active goal without tasks → `GOAL_WITHOUT_TASKS` warning.    |
| 3  | service            | §12(3)   | Task referencing an unknown goal → `UNKNOWN_GOAL_REFERENCE` error. |
| 4  | service            | §12(4)   | Invalid metric → `INVALID_METRIC` error.                     |
| 5  | service            | §12(5)   | Stale activity → `STALE_ACTIVITY` warning.                   |
| 6  | service            | §12(6)   | Multiple simultaneous issue types in one report.            |
| 7  | service            | §12(7)   | Deterministic output: same input → same output.              |
| 8  | service            | §12(8)   | Explicit `now` handling: stale detection depends on `now`.   |
| 9  | CLI                | §12(9)   | Human-readable CLI output contains expected sections + issue codes. |
| 10 | CLI                | §12(10)  | JSON CLI output is valid, complete JSON (counts, issues, codes, severity, IDs, details). |
| 11 | CLI                | §12(11)  | CLI exit code non-zero when error-severity issues present.    |
| 12 | CLI                | §12(12)  | CLI exit code 0 when only warnings (no errors) present.       |

## Expected behaviors

- Read-only: the audit must not modify goals, tasks, metrics, or Kanban state.
- Deterministic: same input state → same structured output.
- Exit codes: `0` when no errors; non-zero when one or more `error`-severity issues.
- Freshness uses an explicit reference time (`now`), not wall-clock alone.

## Acceptance criteria

- `janus goal audit` exists and is wired through `main()`.
- `janus goal audit --json` produces valid JSON.
- All four issue codes are implemented and testable.
- Comprehensive unit and CLI tests exist (this document + `tests/test_goal_integrity_audit.py`).
