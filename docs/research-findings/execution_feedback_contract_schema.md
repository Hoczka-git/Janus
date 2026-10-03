# Canonical Contract Schema — Hermes Execution Feedback → Janus State Updates

**Task:** t_f3f7ebcc
**Date:** 2026-10-03
**Status:** Draft for review
**Parent findings:** `docs/research-findings/triage_contract_synthesis_findings.md`
**Verified against:** Source code at `wt/t_f3f7ebcc` (branch `wt/t_f3f7ebcc`)

---

## 0. Reconciliation Notes (Draft → Reality)

The prior draft at this path contained inaccuracies vs. the actual implementation. This version corrects them:

| Draft claim | Actual code | Correction |
|---|---|---|
| `metadata` has `skill_name` optional | `JanusDomainMetadata.skill_name: str \| None` exists | Confirmed — kept optional |
| `metadata` has only `object`, `title`, `skill_name` | `JanusDomainMetadata` also has `changed_files`, `tests_passed`, `pr_url` | Added to contract |
| Wire format is `ExecutionFeedbackMessage` | Actual type is `ExecutionResultMessage` (metadata + evidence) | Renamed to match existing code |
| Integrity envelope does not exist | No checksum/signature anywhere | Added as new required layer |
| `metric_updates` has `source` field | Actual entries are `dict` with `metric_name`/`value`/`unit`; no `source` | Removed `source` from contract; added to `MetricUpdate` spec as required |
| `_apply_metric_value` accepts `task_id` | Signature: `(goal, new_value, incoming_source, task_id)` | Contract reflects actual |
| Goal gates re-read after metric update | Gates run **before** metric update (P0-4 confirmed) | Contract mandates re-read as caller responsibility |

---

## 1. Wire Format — `ExecutionResultMessage` (extended)

The canonical JSON wire format between Hermes and Janus. Extends the existing `ExecutionResultMessage` with `version` and `integrity` layers.

```json
{
  "version": "1.0",
  "schema": "execution_feedback_v1",
  "message_id": "uuid-v4",
  "timestamp": "ISO-8601 UTC",
  "metadata": { ... },
  "evidence": { ... },
  "integrity": { ... }
}
```

### 1.1 `metadata` (required) — `JanusDomainMetadata`

| Field | Type | Required | Description |
|---|---|---|---|
| `object` | `"goal" \| "task" \| "milestone" \| "project" \| "research" \| "finding" \| "decision"` | yes | Janus domain entity type |
| `title` | `string` | yes | Exact title of the target entity |
| `changed_files` | `list[string]` | no | Defaults to `[]` |
| `tests_passed` | `bool \| null` | no | Test result evidence |
| `pr_url` | `string \| null` | no | PR URL if applicable |
| `skill_name` | `string \| null` | no | Optional skill label for evidence tracking |

**Source:** `src/janus/services/execution_feedback.py:117-151` (`JanusDomainMetadata` dataclass).

### 1.2 `evidence` (required) — `EvidencePackage`

| Field | Type | Required | Description |
|---|---|---|---|
| `task_id` | `string` | yes | Kanban task ID that completed |
| `summary` | `string` | yes | Human-readable completion summary |
| `completed_at` | `string \| null` | no | ISO-8601 UTC timestamp |
| `changed_files` | `list[string]` | no | Defaults to `[]` |
| `tests_passed` | `bool \| null` | no | Test result evidence |
| `pr_url` | `string \| null` | no | PR URL if applicable |
| `body` | `string \| null` | no | Full task body (research/decision ingestion) |
| `janus_body` | `string \| null` | no | Clean artifact body (design §7.3 Option A) |
| `metric_updates` | `list[MetricUpdate]` | no | Declarative metric advancement (design §6.2) |

**Source:** `src/janus/services/execution_feedback.py:32-100` (`EvidencePackage` dataclass).

### 1.3 `integrity` (required) — `IntegrityEnvelope` (NEW)

| Field | Type | Required | Description |
|---|---|---|---|
| `checksum` | `string` | yes | SHA-256 hex digest of `message_id + timestamp + evidence` canonical JSON |
| `producer` | `"hermes" \| string` | yes | Identifies the Hermes worker instance |

**Rationale (P0-5):** Currently no integrity/authenticity check anywhere in the pipeline. A compromised Hermes worker can forge `tests_passed`/`pr_url`. This envelope provides detection capability; verification is a consumer responsibility.

---

## 2. `MetricUpdate` — Declarative Metric Advancement

Addresses P0-2 (undefined `metric_updates` schema).

```json
{
  "metric_name": "string (must match goal.metric_name)",
  "value": "number (required, numeric)",
  "unit": "string | null",
  "source": "task_derived | measurement | import | manual"
}
```

| Constraint | Rule |
|---|---|
| `metric_name` | Required. Must match the target goal's `metric_name` or the update is silently skipped (P0-7 → warning logged) |
| `value` | Required, must be a valid number |
| `unit` | Optional. Propagated to `goal.metric_unit` only when goal has no unit (P0-3: no silent override) |
| `source` | Optional, defaults to `"task_derived"` |

**Source:** `src/janus/services/goals.py:498-522` (`update_goal_progress`), `src/janus/services/goals.py:58-100` (`_apply_metric_value`).

---

## 3. State Update Operations Janus Must Support

### 3.1 `update_goal_progress` (goal)

**Inputs:** `metadata.title`, `evidence.task_id`, `evidence.summary`, `evidence.metric_updates`

**Behavior:**
1. Append/replaces activity entry in `goal.recent_activity` (idempotent by `task_id`)
2. Applies each `MetricUpdate` via `_apply_metric_value` with provenance `task_derived`
3. Propagates `unit` only if `goal.metric_unit` is unset (P0-3 fix: warn on mismatch)
4. Appends `MetricSnapshot` on accepted value mutation
5. Returns updated Goal

**Error signaling:** Raises `ValueError` if goal not found. Returns rejected metric updates with reason string.

**Source:** `src/janus/services/goals.py:402-522`.

### 3.2 `complete_janus_task` (task)

**Inputs:** `metadata.title`, `evidence` dict

**Behavior:**
1. Enforces ADR-004 unified completion gates (`run_unified_completion_gates`)
2. Calls `complete_janus_task` with evidence dict
3. Returns `VerificationResult` under `"verification"` key

**Error signaling:** Raises `UnifiedCompletionGateError` on gate failure. Returns `blocked` status on enforcement gate denial.

**Source:** `src/janus/services/tasks.py:708-1000`, `src/janus/services/tasks.py:1343-1457`.

### 3.3 `update_milestone_status` (milestone)

**Inputs:** `metadata.title`, `evidence.task_id`, `evidence` dict

**Behavior:** Checks threshold, marks milestone complete.

**Source:** `src/janus/services/milestones.py` (referenced via `dispatch_completion`).

### 3.4 `complete_project_by_title` (project)

**Inputs:** `metadata.title`, `evidence` dict

**Source:** `src/janus/services/projects.py` (referenced via `dispatch_completion`).

### 3.5 `_ingest_research` / `_ingest_decision` (research | finding | decision)

**Inputs:** `metadata`, `evidence.body` / `evidence.janus_body`

**Behavior:** Parses and persists markdown artifact. Returns `{"skipped": ...}` when no body present.

**Note:** `_ingest_research` returns `{"research": ...}` for both research and finding (indistinguishable — P1 ambiguity, not P0).

**Source:** `src/janus/services/execution_feedback.py:1008-1071`, `1198-1272`.

---

## 4. Versioning Strategy

- `version` field in `ExecutionResultMessage`: semver `"major.minor"`
- `schema` field: string constant `"execution_feedback_v{major}"` for migration routing
- **Backward compatibility:** Consumers must accept `version` ≤ own version. Unknown fields ignored.
- **Forward compatibility:** Producers must not add required fields in minor versions. Optional fields only.
- Breaking changes (removing fields, changing types) → major version bump → new `schema` string.

---

## 5. Error and Edge-Case Signaling

### 5.1 Dispatch Result Shape

`dispatch_completion` returns a dict with entity-type keys and a `"status"` or `"error"` key:

Success:
```json
{
  "goal": { ... },
  "status": "ok"
}
```

Blocked by enforcement gate:
```json
{
  "status": "blocked",
  "blocked_entity": "task",
  "reason": "...",
  "category": "approval_required | enforcement_blocked | gate_failed"
}
```

Unknown entity type:
```json
{
  "skipped": "object_type",
  "reason": "no handler for domain object"
}
```

**Source:** `src/janus/services/execution_feedback.py:792-995`.

### 5.2 Edge-Case Coverage

| Edge Case | Contract Behavior |
|---|---|
| `metric_updates` for non-goal entity (P0-7) | Warning logged, result includes `"skipped_metric_updates": true` |
| Unit mismatch between update and goal (P0-3) | Warning logged, `goal.metric_unit` unchanged |
| Partial failure in multi-service dispatch (P0-6) | Result dict includes per-entity status; errors collected under `"errors"` list |
| Duplicate `task_id` (idempotency) | Existing entry replaced, no double-application |
| Missing `metadata.object` | `ValueError` raised at parse time |
| Unknown `metadata.object` | Result includes `"skipped": object_name`, warning logged |
| `metric_updates` entry missing `metric_name` or `value` | Entry skipped, warning logged |
| Integrity check failure | Message rejected before any state mutation |
| Goal gate race (P0-4) | Gate re-reads goal state after metric update (caller responsibility, documented in contract) |

### 5.3 Compensation Logging (P0-6, non-rollback)

On partial failure, each successful mutation is logged with:
- `task_id`
- Entity type + title
- Operation performed
- Timestamp
- Error context for failed operations

No automatic rollback — compensation log enables manual remediation.

**Source:** Synthesis §6.4: "compensation logging only, no rollback protocol".

---

## 6. P0 Risk Coverage Matrix

| Risk | Schema/Contract Mitigation |
|---|---|
| **P0-1** No schema validation | `ExecutionResultMessage` with typed fields; `from_dict` validates required fields |
| **P0-2** Undefined `metric_updates` | `MetricUpdate` struct with required `metric_name` + `value` |
| **P0-3** Unit propagation | `unit` field in `MetricUpdate`; explicit mismatch warning |
| **P0-4** Gate race condition | Gate re-reads goal state after metric update (caller responsibility, documented in contract) |
| **P0-5** No integrity check | `IntegrityEnvelope` with SHA-256 checksum + producer ID |
| **P0-6** No partial-failure rollback | Per-entity status in dispatch result; compensation logging |
| **P0-7** Silent ignore for non-goal | Explicit `"skipped_metric_updates"` flag + warning |

---

## 7. Open Questions (Not Resolved by This Schema)

1. **Hermes worker side** — contract is Janus-side only; actual Hermes worker code not in repo. Payload contract assumes worker sends fields matching `EvidencePackage` fields.
2. **Metric updates on non-goal objects** — schema allows `metric_updates` on any entity; the dispatch layer decides silently skip (P0-7 resolution: warning, not error).
3. **Cross-process race conditions** — contract assumes single-host Hermes; multi-host TOCTOU mitigation not addressed.
4. **`_ingest_research` returns same shape for research and finding** — P1 ambiguity, not in P0 scope.
5. **Integrity verification on consumer side** — checksum is produced here; verification logic needs to be added to `dispatch_completion` or a pre-processing layer.

---

## 8. Implementation References

| File | Lines | Role |
|---|---|---|
| `src/janus/services/execution_feedback.py` | 32-100 | `EvidencePackage` dataclass (needs validation) |
| `src/janus/services/execution_feedback.py` | 117-175 | `JanusDomainMetadata` frontmatter dataclass |
| `src/janus/services/execution_feedback.py` | 195-260 | `ExecutionResultMessage` (existing wire format) |
| `src/janus/services/execution_feedback.py` | 792-995 | `dispatch_completion()` router |
| `src/janus/services/goals.py` | 402-522 | `update_goal_progress()` (unit propagation) |
| `src/janus/services/goals.py` | 58-100 | `_apply_metric_value()` (unit logic) |
| `plugins/janus_sync/__init__.py` | 665-667 | `_build_evidence()` |
| `src/janus/services/goal_gates.py` | 53 | Goal completion gates |
| `src/janus/services/tasks.py` | 708-1000 | `run_unified_completion_gates()` |

---

*Verified against source code at `wt/t_f3f7ebcc`. All line references checked against current branch state.*