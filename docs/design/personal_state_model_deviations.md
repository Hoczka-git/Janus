# Personal State Model — Implementation Deviations and Assumptions

**Date:** 2026-09-29
**Task:** t_b1035539
**Spec:** `docs/design/personal_state_model_spec.md`

---

## Deviations from Spec

### 1. PersonalStateStatus field added (not in spec)

The spec defines `PersonalStateStatus` as a concept but does not include it as a field in the `PersonalState` dataclass. The implementation adds a `status: PersonalStateStatus` field to provide an overall classification of the state. This is a read-only derived field that does not affect any write operations.

**Rationale:** The spec mentions "Overall state classification" in the status enum description but does not include it in the field list. The implementation adds it for completeness.

### 2. FollowUp ID format

The spec assumes followup IDs are stored as-is (e.g., "fu-1"). The actual `markdown_followups` parser strips the "fu-" prefix, so `FollowUp.id` is "1" not "fu-1". The goal's `followup_ids` field stores the full "fu-1" format.

**Impact:** Tests must account for this difference when verifying followup linkage.

### 3. Completed tasks filtered by parser

The `markdown_tasks` parser filters out completed tasks (lines starting with `- [x]`). This means `PersonalState.tasks` only contains open tasks, not all tasks.

**Impact:** Tests must expect only open tasks in the aggregate.

### 4. Metric field names in goals.md

The spec uses `metric_name`, `metric_unit`, `start_value`, `current_value`, `target_value` as field names. The actual `markdown_goals` parser expects `Metric:`, `Unit:`, `Start:`, `Current:`, `Target:` (without the "value" suffix).

**Impact:** Test data must use the actual parser format.

### 5. Recent activity format

The spec shows `recent_activity` as a list of dicts. The actual parser expects JSON in comment lines (`# {...}`) within a `## Recent activity` section.

**Impact:** Test data must use the JSON comment format.

---

## Assumptions

### 1. Read-model boundary

`PersonalState` is strictly a read-model. It has no write methods (`save`, `update`, `delete`, `write`). All writes go through existing service functions. This is enforced by the dataclass design.

### 2. Fingerprint-based caching

The `data_fingerprint` is a SHA-256 hash of all source data files. If any file changes, the fingerprint changes and the aggregate must be rebuilt. Files that do not exist are skipped (they contribute nothing to the fingerprint).

### 3. Immutable aggregate

`PersonalState` is constructed on demand and is not persisted. It provides a snapshot that may be slightly stale if source files change during construction.

### 4. Integrity audit is optional

The integrity audit is included by default but can be disabled via `include_integrity_audit=False`. This allows for faster builds when integrity checking is not needed.

### 5. Strategic summary and recommended actions are opt-in

Both `include_strategic_summary` and `include_recommended_actions` default to `False` because they are expensive computations. Callers must explicitly request them.

### 6. Empty state handling

When no source data files exist or all are empty, `PersonalState` is still returned with empty lists and `is_empty == True`. This is not an error condition.

### 7. Orphan tasks are warnings, not errors

Tasks not linked to any goal are flagged as warnings by the integrity audit, not errors. This is because orphan tasks may be intentional (e.g., standalone tasks).

---

## Test Coverage

### Unit tests (test_personal_state.py — 61 tests)

- Construction and validation
- PersonalStateStatus enum
- Derived properties (is_empty, has_integrity_errors, counts)
- Transition rules (goal, task, followup)
- Serialization (to_dict)

### Builder tests (test_personal_state_builder.py — 65 tests)

- Data fingerprint computation
- Derived views (active goals, open tasks, blocked tasks, etc.)
- Data loading from markdown files
- Integrity audit integration
- Edge cases (empty state, missing files)
- Integration with existing services

### Integration tests (test_personal_state_integration.py — 77 tests)

- End-to-end build from real data files
- Cross-cutting queries (goal-task, goal-milestone-project, goal-followup, goal-metric, goal-research, goal-decision, goal-activity)
- Integrity and invariant enforcement (PS-1 through PS-10)
- Cache invalidation (fingerprint changes)
- Lifecycle coordination
- Spec compliance (all 23 fields, transition rules, invariants)
- Edge cases (empty state, missing files, None state tasks)
- Performance and stress (100 goals, 500 tasks)
- Serialization round-trip
- Integration with existing services

**Total:** 203 tests for the Personal State Model

---

## Verification

- All 203 personal state tests pass
- Full test suite: 2922 tests pass, 0 failures
- No regressions in existing functionality
