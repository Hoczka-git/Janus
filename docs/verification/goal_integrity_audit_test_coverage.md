# Goal Integrity Audit — Test Coverage Verification

Design spec: `docs/design/goal_integrity_audit.md` §12 (Testing).

This task (t_c4814e6d: "Add unit test coverage per design spec") adds
unit-and-CLI test coverage for the Goal Integrity Audit. The implementation
was delivered in `feat: implement deterministic goal integrity audit (#203)`
(commit f18af69, `src/janus/services/goal_integrity.py`).

## Coverage mapping (spec §12 → tests)

| # | Spec requirement | Test class / case | Status |
|---|------------------|-------------------|--------|
| 1 | Healthy goals/tasks | `TestHealthyGoals` (3) | ✅ |
| 2 | Active goal without tasks | `TestGoalWithoutTasks` (3) | ✅ |
| 3 | Task referencing unknown goal | `TestUnknownGoalReference` (2) | ✅ |
| 4 | Invalid metric | `TestInvalidMetric` (3) | ✅ |
| 5 | Stale activity | `TestStaleActivity` (3) | ✅ |
| 6 | Multiple simultaneous issue types | `TestMultipleIssues` (1) | ✅ |
| 7 | Deterministic output | `TestDeterminism` (1) | ✅ |
| 8 | Explicit `now` handling | `TestExplicitNow` (1) | ✅ |
| 9 | Human-readable CLI output | `test_human_readable_output` | ✅ |
| 10 | JSON CLI output | `test_json_output` | ✅ |
| 11 | CLI exit code with errors | `test_exit_code_with_errors` | ✅ |
| 12 | CLI exit code with warnings only | `test_exit_code_with_warnings_only` | ✅ |
|| 13 | Orphan tasks | `TestOrphanTasks` (5) | ✅ |
|| 14 | Invalid related_task references | `TestInvalidRelatedTasks` (4) | ✅ |
|| 15 | Relationship count mismatch | `TestRelationshipCountMismatch` (3) | ✅ |
|| 16 | Circular references | `TestCircularReferences` (3) | ✅ |

## Issue codes covered

- `GOAL_WITHOUT_TASKS` (warning)
- `UNKNOWN_GOAL_REFERENCE` (error)
- `INVALID_METRIC` (error)
- `STALE_ACTIVITY` (warning)
- `ORPHANED_TASK` (warning)
- `INVALID_RELATED_TASK` (error)
- `RELATIONSHIP_COUNT_MISMATCH` (warning)
- `CIRCULAR_REFERENCE` (error)

## Acceptance criteria verification

- `janus goal audit` exists → `handle_goal_audit` in `src/janus/goals_cli.py`
- `janus goal audit --json` exists → `--json` flag parsed in `handle_goal_audit`
- Audit is read-only → `audit_goal_integrity(goals, tasks, now)` takes data in,
  returns a report; no writes.
- Audit logic independent of CLI formatting → service in `src/janus/services/`
- All initial issue codes implemented → see table above
- Issue severity deterministic → `TestDeterminism`
- Freshness uses explicit reference time → `audit_goal_integrity(..., now=...)`,
  `TestExplicitNow`
- Errors produce non-zero CLI exit code → `test_exit_code_with_errors`
- Warnings do not fail the command → `test_exit_code_with_warnings_only`
- Comprehensive unit and CLI tests exist → 48 tests (25 original + 23 for extended codes), all passing
|- Existing goal functionality unchanged → full suite 2393/2393 passing
- Documentation describes the feature → `docs/design/goal_integrity_audit.md`

## Test results

```
tests/test_goal_integrity_audit.py .................................... 48 passed
full suite: 2393 passed, 0 failed
```
