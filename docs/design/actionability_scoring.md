# Actionability Scoring Filter — Design

## Overview

The actionability scoring filter is a distinct, testable stage that sits between
problem detection (`audit_goal_integrity`) and task creation. Each detected
problem is scored for actionability; actionable problems trigger task creation
while non-actionable ones are recorded without side effects.

## Pipeline Flow

```
detected problems → score_actionability() → actionable? → yes → create task
                                                    → no  → record only
```

## Actionability Criteria

A problem is **actionable** when its computed score meets or exceeds a
configurable threshold (default: **40**).

### Scoring Algorithm

The score is the sum of four deterministic factors:

| Factor | Condition | Points |
|--------|-----------|--------|
| **Severity** | `error` | +50 |
| | `warning` | +30 |
| | `info` | +10 |
| **Repair path** | Issue code has a known deterministic repair | +20 |
| **Context completeness** | Both `goal_id` and `task_id` present | +10 |
| **Structured details** | `details` dict is non-empty | +10 |

### Repairable Codes

The following issue codes have deterministic repair paths (from
`goal_integrity_repair`):

- `UNKNOWN_GOAL_REFERENCE`
- `INVALID_RELATED_TASK`
- `CIRCULAR_REFERENCE`
- `ORPHANED_TASK`
- `RELATIONSHIP_COUNT_MISMATCH`

### Score Ranges

- **Minimum**: 0 (unknown severity, no repairable code, no context, no details)
- **Maximum**: 100 (error + repairable + full context + details)
- **Default threshold**: 40

### Examples

| Issue | Severity | Repairable | Context | Details | Score | Actionable? |
|-------|----------|------------|---------|---------|-------|-------------|
| Unknown goal ref, full context | error | yes | yes | yes | 90 | yes |
| Orphaned task, warning | warning | yes | no | no | 50 | yes |
| Stale activity, warning + context | warning | no | yes | no | 40 | yes |
| Stale activity, warning only | warning | no | no | no | 30 | no |
| Info-level healthy check | info | no | no | no | 10 | no |

## API

### `score_actionability(issue, threshold=40) → ActionabilityResult`

Scores a single `GoalIntegrityIssue` and returns an `ActionabilityResult` with:
- `score`: computed actionability score
- `is_actionable`: whether score >= threshold
- `reasons`: human-readable list of scoring factors
- `suggested_task_title`: task title if actionable, else `None`
- `suggested_task_metadata`: metadata dict if actionable, else `{}`

### `filter_actionable(issues, threshold=40) → ActionabilityReport`

Scores a batch of issues and returns an `ActionabilityReport` with:
- `results`: one `ActionabilityResult` per input
- `actionable`: subset that passed the threshold
- `recorded`: subset that did not pass
- `evaluated_at`: timestamp

### `create_tasks_for_actionable(report, task_creator=None) → list[Task]`

Creates tasks for all actionable results. Non-actionable results are logged
(recorded) without task creation. The `task_creator` parameter allows
dependency injection for testing.

### `run_actionability_pipeline(issues, threshold=40, task_creator=None) → (ActionabilityReport, list[Task])`

Convenience function combining `filter_actionable` and
`create_tasks_for_actionable`.

## Integration Point

The filter is inserted into `handle_goal_audit` in `goals_cli.py` after
`audit_goal_integrity` returns its report. The audit report's `issues` list
is passed to `run_actionability_pipeline`, which creates tasks for actionable
problems and logs non-actionable ones.

## Non-Goals

- Does not modify the audit detection logic
- Does not persist non-actionable issues to a database (logging only)
- Does not attempt automatic repair — only task creation
