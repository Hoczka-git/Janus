# Goal Integrity Audit

**Status:** Implemented
**Domain:** Goals / Tasks
**Type:** Deterministic domain audit
**CLI:** `janus goal audit`

## 1. Purpose

Goal Integrity Audit provides a deterministic health check of the relationship between Janus Goals, Tasks, metrics, and recent activity.

The feature should detect structural problems that can cause goals to become ineffective or disconnected from actual work.

The audit is intentionally read-only. It must not modify goals, tasks, metrics, Kanban state, or execution state.

The audit is a diagnostic capability, not a replacement for goal health scoring.

## 2. Motivation

Janus currently supports goal health, progress tracking, goal-aware task planning, and execution feedback.

However, the current system can contain inconsistencies such as:

* an active goal without any actionable task;
* a task referencing a goal that does not exist;
* invalid or incomplete metric configuration;
* a goal that has no recent activity;
* goal/task metadata that is structurally inconsistent.

These problems should be detectable deterministically before they affect autonomous planning.

The audit also provides a lightweight verification surface for the Goal → Task relationship.

## 3. Scope

### In scope

The audit must inspect:

1. Goal/task linkage.
2. Goal metric configuration.
3. Goal activity freshness.
4. References from tasks to goals.
5. Overall integrity summary.

### Out of scope

The first implementation must not:

* modify goal state;
* modify task state;
* automatically create tasks;
* update goal metrics;
* invoke LLMs;
* call external APIs;
* change the ADR-004 completion path;
* introduce scheduling or background execution;
* replace existing goal health calculations.

## 4. Audit Model

The audit returns a structured `GoalIntegrityReport`.

Conceptually:

```text
GoalIntegrityReport
├── goals_checked
├── tasks_checked
├── issues[]
├── healthy_checks[]
├── error_count
├── warning_count
└── info_count
```

Each issue is represented by `GoalIntegrityIssue`.

```text
GoalIntegrityIssue
├── code
├── severity
├── goal_id
├── task_id
├── message
└── details
```

The exact Python representation should follow existing Janus model conventions.

## 5. Severity

Three severity levels are supported:

### error

A structural inconsistency that should normally be fixed.

Examples:

* task references an unknown goal;
* goal contains invalid metric configuration.

### warning

A potentially problematic state that may be intentional.

Examples:

* active goal has no open/actionable tasks;
* goal has stale activity.

### info

A useful diagnostic observation that does not represent a problem.

Examples:

* goal has valid task linkage;
* goal has recently updated activity.

## 6. Issue Codes

The initial implementation should support these deterministic issue codes.

### `GOAL_WITHOUT_TASKS`

An active goal has no related open/actionable tasks.

Severity: `warning`

The audit should not flag completed or intentionally inactive goals unless existing goal semantics require otherwise.

### `UNKNOWN_GOAL_REFERENCE`

A task references a goal ID that does not exist.

Severity: `error`

The issue should identify both the task and the invalid goal reference.

### `INVALID_METRIC`

A goal contains an invalid metric configuration.

Severity: `error`

The implementation should reuse existing goal/metric validation rules rather than introducing a second definition of valid metrics.

### `STALE_ACTIVITY`

An active goal has not received relevant activity within the configured freshness threshold.

Severity: `warning`

The threshold must be deterministic and documented. It should reuse an existing Janus constant/configuration if one already exists; otherwise introduce a small explicit constant rather than making the value configurable through an external service.

## 7. Determinism

The audit must produce the same result for the same input state.

It must not depend on:

* LLM output;
* wall-clock time without an explicitly supplied/reference timestamp;
* external APIs;
* network state;
* task execution;
* random values.

Where freshness depends on the current time, the service should accept `now` as an explicit input. This makes the core audit deterministic and straightforward to test.

## 8. Service Boundary

The audit logic should live in a domain/service layer rather than in the CLI.

Conceptually:

```python
report = audit_goal_integrity(
    goals=goals,
    tasks=tasks,
    now=now,
)
```

The service should:

1. receive domain data;
2. validate relationships;
3. produce structured issues;
4. return a complete report.

Persistence loading and CLI formatting should remain outside the core audit logic.

## 9. CLI

Add:

```bash
janus goal audit
```

The default output should be human-readable.

Example:

```text
Goal Integrity Audit

Goals checked: 31
Tasks checked: 74

Issues:
  ⚠ GOAL_WITHOUT_TASKS       12
  ⚠ STALE_ACTIVITY            4
  ✗ UNKNOWN_GOAL_REFERENCE    3
  ✗ INVALID_METRIC             2

Summary:
  Errors:   5
  Warnings: 16
  Info:     18
```

The CLI should provide enough context to identify the affected goal/task without requiring the user to inspect the database manually.

## 10. JSON Output

Add:

```bash
janus goal audit --json
```

The output must be valid machine-readable JSON.

The JSON representation should contain the complete structured report, including:

* counts;
* issues;
* issue codes;
* severity;
* affected goal/task IDs;
* diagnostic details.

The JSON schema should remain stable enough for future automation.

## 11. Exit Codes

The CLI should return:

* `0` — no errors;
* non-zero — one or more `error` severity issues.

Warnings alone should not cause failure.

This makes the command suitable for future automated verification without making normal stale-goal warnings fatal.

## 12. Testing

Tests must cover at least:

1. healthy goals/tasks;
2. active goal without tasks;
3. task referencing an unknown goal;
4. invalid metric;
5. stale activity;
6. multiple simultaneous issue types;
7. deterministic output;
8. explicit `now` handling;
9. human-readable CLI output;
10. JSON CLI output;
11. CLI exit code with errors;
12. CLI exit code with warnings only.

The tests should validate structured issue codes rather than relying exclusively on formatted strings.

## 13. Non-Goals

The following are explicitly deferred:

* automatic repair;
* automatic task creation;
* automatic metric updates;
* autonomous remediation;
* Telegram integration;
* scheduled execution;
* LLM-based diagnosis;
* integration with the ADR-004 completion path.

These may be considered later if the audit proves useful.

## 14. Future Extension

The report should be designed so additional checks can be added without changing the CLI contract.

Potential future checks include:

* orphaned milestones;
* broken project relationships;
* goals with completed tasks but no progress;
* inconsistent goal/task metadata;
* goals whose metric has not been updated despite completed related work.

These are intentionally not part of the first implementation.

## 15. Acceptance Criteria

The feature is complete when:

* `janus goal audit` exists;
* `janus goal audit --json` exists;
* the audit is read-only;
* audit logic is independent of CLI formatting;
* all initial issue codes are implemented;
* issue severity is deterministic;
* freshness uses an explicit reference time;
* errors produce a non-zero CLI exit code;
* warnings do not fail the command;
* comprehensive unit and CLI tests exist;
* existing goal functionality remains unchanged;
* documentation describes the feature;
* affected tests pass.

## 16. Architectural Constraint

Goal Integrity Audit belongs to Janus domain logic.

Hermes should only be responsible for orchestration or future scheduling of the audit.

The implementation must follow the architectural principle:

> Build domain capabilities in Janus. Reuse Hermes for agent orchestration whenever possible.
