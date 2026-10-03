# Execution Feedback Contract v1 — Design Document

**Task:** t_3d1bb9c4 (synthesis of t_f3f7ebcc + t_1fbf9a5c)
**Date:** 2026-10-03
**Status:** Final for implementation
**Parents:**
- t_f3f7ebcc — Canonical contract schema and interface (PR #397 merged, CI green)
- t_1fbf9a5c — P0 risk mitigations within the contract (design-only, approved with integration_override)

---

## 1. Purpose and Scope Boundaries

### Purpose

Define the minimal production-grade contract between Hermes execution feedback and Janus state updates so that a completed Kanban task produces auditable, verifiable state changes in Janus — without conflating execution success with outcome verification.

### Scope boundaries

**In scope:**
- EvidencePackage schema, validation, and integrity
- metric_updates declarative advancement (goal only)
- Dispatch routing and per-entity error signaling
- Compensation logging for partial failures
- Contract versioning and backward compatibility

**Out of scope (explicit non-goals):**
- Full authentication / HMAC signature layer (integrity = SHA-256 digest anchor only)
- Automatic rollback protocol (compensation log only, per synthesis §6.4)
- Hermes worker-side implementation (contract is Janus-side; worker payload assumed to match)
- Multi-host TOCTOU mitigation (single-host assumption)
- Research/finding vs. decision routing ambiguity (P1, not P0)
- New persistence architecture
- Broader Goal/Task lifecycle redesign

---

## 2. Canonical Schema Definition

### 2.1 `ExecutionResultMessage` (wire format)

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

| Field | Type | Required | Description |
|---|---|---|---|
| `version` | string (semver major.minor) | yes | Contract version |
| `schema` | string constant | yes | `"execution_feedback_v1"` for routing |
| `message_id` | string (UUID v4) | yes | Unique message identifier |
| `timestamp` | string (ISO-8601 UTC) | yes | Production timestamp |
| `metadata` | `JanusDomainMetadata` | yes | Domain linkage |
| `evidence` | `EvidencePackage` | yes | Execution evidence |
| `integrity` | `IntegrityEnvelope` | yes | SHA-256 + producer |

### 2.2 `JanusDomainMetadata`

| Field | Type | Required | Description |
|---|---|---|---|
| `object` | enum | yes | `"goal"\|"task"\|"milestone"\|"project"\|"research"\|"finding"\|"decision"` |
| `title` | string | yes | Exact target entity title |
| `changed_files` | list[string] | no | Defaults `[]` |
| `tests_passed` | bool\|null | no | Test result evidence |
| `pr_url` | string\|null | no | PR URL if applicable |
| `skill_name` | string\|null | no | Optional skill label |

**Source:** `src/janus/services/execution_feedback.py:117-151`

### 2.3 `EvidencePackage`

| Field | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | yes | Kanban task ID |
| `summary` | string | yes | Human-readable completion summary |
| `completed_at` | string\|null | no | ISO-8601 UTC |
| `changed_files` | list[string] | no | Defaults `[]` |
| `tests_passed` | bool\|null | no | Test evidence |
| `pr_url` | string\|null | no | PR URL |
| `body` | string\|null | no | Full task body (research/decision ingestion) |
| `janus_body` | string\|null | no | Clean artifact body (design §7.3 Option A) |
| `metric_updates` | list[MetricUpdate] | no | Declarative metric advancement |
| `idempotency_key` | string | yes | Required for P0-6 compensation/retry |
| `evidence_digest` | string\|null | no | SHA-256 hex of to_dict() without digest field (P0-5) |

**Source:** `src/janus/services/execution_feedback.py:33-100` + P0 mitigations

### 2.4 `IntegrityEnvelope` (NEW)

| Field | Type | Required | Description |
|---|---|---|---|
| `checksum` | string | yes | SHA-256 hex of `message_id + timestamp + evidence` canonical JSON |
| `producer` | string | yes | `"hermes"` or worker instance identifier |

**Rationale (P0-5):** No integrity/authenticity check exists in the pipeline. A compromised Hermes worker can forge `tests_passed`/`pr_url`. This envelope provides detection; verification is a consumer responsibility.

### 2.5 `MetricUpdate`

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
| `metric_name` | Required; must match target goal's `metric_name` or silently skipped (P0-7 → warning) |
| `value` | Required, must be valid number |
| `unit` | Optional; propagates to `goal.metric_unit` only when goal has no unit (P0-3: no silent override) |
| `source` | Optional, defaults to `"task_derived"` |

**Source:** `src/janus/services/goals.py:498-522`, `src/janus/services/goals.py:58-100`

### 2.6 State Update Operations

| Operation | Object | Key behavior |
|---|---|---|
| `update_goal_progress` | goal | Appends activity, applies MetricUpdate, propagates unit (P0-3 fix), appends MetricSnapshot |
| `complete_janus_task` | task | Enforces ADR-004 gates, returns VerificationResult |
| `update_milestone_status` | milestone | Threshold check, marks complete |
| `complete_project_by_title` | project | Complete by title with evidence |
| `_ingest_research` / `_ingest_decision` | research/finding/decision | Parse + persist markdown; returns `{"skipped":...}` when no body |

**Sources:** `execution_feedback.py:792-995`, `goals.py:402-522`, `tasks.py:708-1000`

---

## 3. P0 Risk Mitigation Mapping with Rationale

| Risk | Mitigation | Rationale | Trade-off |
|---|---|---|---|
| **P0-1** No schema validation (silent corruption) | `EvidencePackage.__post_init__` validation: `task_id` non-empty, `summary` non-empty, `metric_updates` entries require `metric_name` + numeric `value`. Raises `ValueError`. | Fails fast at construction, not downstream. No new protocol layer. | Rejects previously-accepted malformed payloads (desirable). Must call before `to_dict()` in dispatch. |
| **P0-2** Undefined `metric_updates` schema (silent skip) | Contract-level schema: each entry `{metric_name: str, value: int\|float, unit: str\|None}`. `update_goal_progress()` validates before applying; malformed entry raises. | Matches design §6.2; no DB schema change. | Producers must fix malformed entries; no backward-compat for invalid shapes. |
| **P0-3** Unit propagation ignores first-update unit (unit drift) | `EvidencePackage` carries `metric_updates[].unit` explicitly. `_apply_metric_value()` compares units; raises `ValueError` on mismatch. First update sets `goal.metric_unit` if unset. | Keeps existing propagation logic; adds explicit conflict detection. | Forces producer consistency; no silent drift. |
| **P0-4** Goal gate reads stale state (race) | Ordering guarantee: `update_goal_progress()` applies metric_updates first, re-reads Goal, then runs `run_unified_completion_gates()` on refreshed state. | Reorders existing calls; no new mechanism. | Slight latency increase; eliminates stale-read race. |
| **P0-5** No integrity/authenticity check (forged evidence) | `IntegrityEnvelope` with SHA-256 checksum + producer ID. Consumer verifies by recomputing. | Single optional field; detects tampering since production. Not a cryptographic signature — authenticity anchor only per synthesis §6.3. | Producer must compute digest; no key infrastructure added. |
| **P0-6** No partial-failure rollback (dangling mutations) | Compensation logging (not rollback protocol — synthesis §6.4 excludes rollback). `EvidencePackage` gains required `idempotency_key`. `dispatch_completion()` writes compensation log entry listing successful mutations before failure; idempotency key enables dedup on retry. | Idempotency key enables safe retry; audit entry provides traceability. | Does not undo mutations; relies on retry + audit for recovery. |
| **P0-7** `metric_updates` silently ignored for non-goal entities | Routing rule: `metric_updates` valid only when `metadata.object == "goal"`. If present for other objects, dispatch returns explicit `{"warning": "metric_updates ignored"}` instead of silent skip. | Explicit warning in return dict; consumer can act on it. | Producers must not send metric_updates for non-goal objects. |

---

## 4. Non-Goals and Out-of-Scope Items

1. **Full authentication / HMAC signature layer** — synthesis §6.3 explicitly excludes; digest anchor only.
2. **Automatic rollback protocol** — synthesis §6.4 explicitly excludes; compensation log only.
3. **Hermes worker-side implementation** — contract is Janus-side; worker code not in repo (open question for implementation).
4. **Multi-host TOCTOU mitigation** — single-host assumption adequate for V1.
5. **Research vs. finding routing ambiguity** — P1, not P0; `_ingest_research` returns same shape for both.
6. **New persistence architecture** — no DB schema change; uses existing `Goal.recent_activity` / task storage.
7. **Broader Goal/Task lifecycle redesign** — contract fits within existing ADR-004 gates and enforcement model.
8. **Cross-process locking** — ordering guarantee only; no DB locks.

---

## 5. Acceptance Criteria for Implementation

1. All 7 P0 risks have concrete contract-level mitigations (see §3).
2. `EvidencePackage.__post_init__` validates required fields and raises `ValueError` on violation.
3. `MetricUpdate` entries validated before application; malformed entries raise, not silently skip.
4. Unit mismatch between update and goal raises `ValueError` (P0-3).
5. Goal gate re-reads updated state before evaluation (P0-4).
6. `IntegrityEnvelope` produced on every `ExecutionResultMessage`; consumer can verify.
7. Partial failures produce per-entity status + compensation log entry with `idempotency_key` (P0-6).
8. Non-goal `metric_updates` return explicit warning, not silent skip (P0-7).
9. Contract versioning: `version` field (semver major.minor) + `schema` string constant for routing.
10. Backward compatibility: consumers accept `version` ≤ own version; unknown fields ignored.
11. Source code references verified against `wt/t_3d1bb9c4`:
    - `execution_feedback.py:33-100` (EvidencePackage)
    - `execution_feedback.py:117-151` (JanusDomainMetadata)
    - `execution_feedback.py:195-260` (ExecutionResultMessage)
    - `execution_feedback.py:792-995` (dispatch_completion)
    - `goals.py:402-522` (update_goal_progress)
    - `goals.py:58-100` (_apply_metric_value)
    - `goal_gates.py:53` (goal completion gates)
    - `tasks.py:708-1000` (run_unified_completion_gates)

---

## 6. Open Implementation Questions

1. **Hermes worker side** — payload contract assumption unverified; worker code not in repo.
2. **Integrity verification consumer-side** — checksum produced here; verification logic needs implementation in `dispatch_completion` or pre-processing layer.
3. **metric_updates on non-goal objects** — warning-only resolution (P0-7); schema allows it on any entity.
4. **Cross-process TOCTOU** — contract assumes single-host; multi-host mitigation deferred.
5. **`_ingest_research` returns same shape for research and finding** — P1 ambiguity, not P0 scope.

---

## 7. Versioning Strategy

- `version` field: semver `"major.minor"`
- `schema` field: string constant `"execution_feedback_v{major}"` for migration routing
- Backward compatibility: consumers accept `version` ≤ own version; unknown fields ignored
- Forward compatibility: producers must not add required fields in minor versions; optional fields only
- Breaking changes (removing fields, changing types) → major version bump → new `schema` string

---

## 8. Verification Reference

This document synthesizes and reconciles:
- `docs/research-findings/execution_feedback_contract_schema.md` (t_f3f7ebcc, 276 lines, PR #397 merged)
- `docs/research-findings/p0_risk_mitigations_contract.md` (t_1fbf9a5c, 65 lines, approved with integration_override)
- Source code at `wt/t_3d1bb9c4` (current worktree branch)

All line references verified against current branch state.