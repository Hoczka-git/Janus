# Task Continuation Semantics — Formal Specification

**Task:** t_470ecad0 — Document the designed continuation semantics
**Date:** 2026-09-08
**Status:** Specification ready for implementation
**Parent design:** t_e75fa9e8 — Design task continuation semantics
**integration_required:** false (design/specification task — no PR needed)

---

## 1. Purpose

This document is the authoritative specification for the continuation semantics that govern the transition from a research/design Kanban task to its downstream implementation task(s). It formalizes:

- What state crosses the research/design → implementation boundary
- The trigger model that decides when continuation is allowed
- The validation contract that must pass before an implementation task is promoted to `ready`
- Explicit examples of valid and blocked continuations

Workers implementing the continuation primitives (in `kanban_db.py`, `kanban_continuation.py`, or wherever the implementer places them) should treat this document as the contract. The acceptance criteria in §11 are the verification checklist.

---

## 2. Design Principles

These principles are inherited from the parent design and govern all implementation decisions:

| # | Principle | What it means in practice |
|---|-----------|---------------------------|
| 1 | **Artifact-first, not task-first** | A research task reaching `done` does NOT trigger continuation by itself. The artifact must be finalized. The task state is a precondition; the artifact state is the trigger. |
| 2 | **Explicit contracts, not implicit inference** | Every continuation has a declared `continuation_contract` frontmatter. There is no heuristic, timestamp-based, or "looks-like-it-should-continue" inference. |
| 3 | **Minimal new machinery** | Reuse `recompute_ready`, parent→child gating, lifecycle hooks. Add new primitives only where the existing model is structurally incapable. |
| 4 | **Idempotent and re-entrant** | Completion events, validation calls, and promotion are all safe under repeated invocation — retries, crash recovery, and double-firing must not corrupt state. |
| 5 | **Fail-safe, not fail-soft** | If continuation cannot proceed, the system blocks explicitly with a clear, actionable reason. It does not silently skip, guess, or degrade. |

---

## 3. Scope

### 3.1 In scope

- The `continuation_contract` frontmatter schema (parent side and child side)
- The `should_continue()` trigger resolution logic
- The `validate_continuation_artifacts()` hook and its return contract
- The `create_continuation_task()` helper that creates an implementation task with the contract pre-injected
- The worker-context continuation section that surfaces the contract to the implementation worker
- All three trigger types: artifact_finalized (Trigger A), explicit_handoff (Trigger B), signal (Trigger C — deferred)
- Error classes, recovery paths, idempotency guarantees, and failure isolation
- Backward compatibility: tasks without a `continuation_contract` continue to use standard parent→child gating

### 3.2 Out of scope

- Janus-local `data/tasks.md` task continuation (separate concern — future design)
- Obsidian write integration (ADR-002 concern; the continuation system only reads artifact `status`)
- Automated artifact finalization (marking `status: finalized` is a human decision per ADR-002)
- Full research→finding→decision→action loop automation (this document provides the handoff primitive only)
- Swarm integration inside the continuation contract (swarms can be the implementation phase, but the contract is between the research/design task and the swarm root)
- Signal-based triggers (Trigger C) — deferred to future work

---

## 4. State Preserved Across the Boundary

The research/design → implementation transition is a state transfer: the output of the upstream phase becomes the input context for the downstream phase. The following state must be preserved and transferred. The implementer must ensure that the `create_continuation_task()` helper and the worker context surface these fields.

### 4.1 Mandatory preserved state

| Field | Type | Source | Destination | Purpose |
|-------|------|--------|-------------|---------|
| `artifact_ref` | string (path or URI) | Research/design task body or frontmatter | Implementation task body/frontmatter | Points to the finalized artifact that motivates this implementation |
| `artifact_version` | string (semver or date) | Artifact's frontmatter/version field | Implementation task body | Ensures the implementation targets a specific version, not a moving target |
| `findings_index` | list of finding references | Research artifact's findings section | Implementation task body (or linked child tasks) | Which specific findings motivate which implementation items |
| `decisions_log` | list of decision records | Design artifact's decision log | Implementation task body | Captures design decisions that constrain implementation |
| `open_questions` | list of unresolved items | Research/design artifact | Implementation task body | Items that implementation must resolve or revisit |
| `source_project` | project ID or slug | Research/design task's project linkage | Implementation task's project linkage | Keeps both phases in the same project context |
| `parent_task_id` | Kanban task ID | Research/design Kanban task | Implementation Kanban task (via `parents=`) | Establishes the parent→child gating relationship |

### 4.2 Optional preserved state

| Field | When included | Purpose |
|-------|---------------|---------|
| `confidence_tier` | Research findings have confidence levels | Implementation can prioritize high-confidence findings |
| `knowledge_gaps` | Research identifies gaps | Implementation can target gap-closure work |
| `related_artifacts` | Multiple research artifacts feed one implementation | Implementation sees the full input set |
| `reviewer_context` | Design review produced reviewer notes | Implementation starts with reviewer feedback visible |

### 4.3 What is NOT preserved

- Intermediate working state (drafts, scratch files, experiment logs) — only finalized artifacts cross the boundary.
- Researcher assignee / implementer assignee — each phase has its own assignee; no transfer.
- Task body prose that is phase-internal (research methodology, design process notes) — trimmed to the contract above.
- Temporal state (when the research was done) beyond what's in the artifact's own metadata.

---

## 5. Trigger Model

### 5.1 Trigger types

Three trigger models exist. The trigger type is declared in the `continuation_contract` frontmatter of the **implementation task** (child side). The trigger resolution logic in `should_continue()` uses this declaration to decide whether promotion to `ready` is allowed.

#### Trigger A: Artifact-Finalized (primary)

The research/design phase produces a finalized artifact. Continuation triggers when **all** of the following are true:

1. The research/design Kanban task reaches `done`.
2. The task body or frontmatter contains an `artifact_ref` pointing to a valid, existing artifact.
3. The artifact has a `status: finalized` (or equivalent) marker in its frontmatter/metadata.

This is the standard research→design→implementation pipeline trigger. The artifact is the authoritative signal, not the task state alone.

#### Trigger B: Explicit Handoff Declaration

The researcher/designer explicitly declares that continuation should proceed, independent of artifact finalization:

1. The research/design task body contains `handoff: ready` (or similar explicit marker).
2. The implementation task is created with `parents=[research_task_id]`.
3. `recompute_ready` promotes the implementation task when the parent is `done`.

Used when the artifact is not the gating factor — e.g., the design lives in the researcher's head, or the artifact is a living document that will never be "finalized."

#### Trigger C: Time/Signal-Based (deferred)

Continuation is triggered by an external signal (goal health signal, scheduled review, webhook). Out of scope for this specification; existing replenishment `webhook` source kind covers this pattern.

### 5.2 Trigger resolution logic

The following pseudocode is the contract for `should_continue()`. Any implementation must produce equivalent behavior.

```python
def should_continue(parent_task, child_task) -> tuple[bool, str]:
    """
    Returns (proceed, reason).
    proceed=False means continuation is blocked; reason explains why.
    Called from recompute_ready for child tasks that have a continuation_contract.
    """

    # Pre-condition: parent must be done (standard gating)
    if parent_task.status != "done":
        return False, "parent task not done"

    contract = child_task.continuation_contract  # parsed from body frontmatter

    # No contract at all → standard parent→child gating applies (backward compat)
    if contract is None:
        return True, "no continuation_contract — standard parent→child gating"

    trigger_type = contract.trigger

    if trigger_type == "explicit_handoff":
        # Trigger B: no artifact check needed
        return True, "explicit handoff — no artifact required"

    if trigger_type == "artifact_finalized":
        # Trigger A: artifact-gated
        artifact_ref = contract.artifact_ref
        if not artifact_ref:
            return False, "artifact_finalized trigger declared but artifact_ref is empty"

        artifact = locate_artifact(artifact_ref)
        if not artifact:
            return False, f"artifact not found: {artifact_ref}"

        if artifact.status != "finalized":
            return False, (
                f"artifact not finalized: {artifact_ref} "
                f"(status={artifact.status!r}, expected finalized)"
            )

        return True, "artifact finalized"

    # Unknown trigger type — fail-safe
    return False, f"unknown trigger type: {trigger_type!r}"
```

### 5.3 Trigger storage

The trigger type, artifact reference, version, and parent task ID are stored in the **implementation task's body frontmatter**, not in a separate table. This makes the contract self-contained — readable by workers, auditable via git, and queryable via text search.

**Child (implementation task) frontmatter:**

```yaml
---
continuation_contract:
  triggered_by: artifact_finalized        # | explicit_handoff
  artifact_ref: companies/GLUE/knowledge.md
  artifact_version: "2026-09-08"
  parent_task_id: t_0a94c6c3
  required_artifacts:
    - path: companies/GLUE/knowledge.md
      status: finalized
    - path: companies/GLUE/reports/2026-09-08.md
      status: finalized
---
```

**Parent (research/design task) frontmatter** (optional, declares intent):

```yaml
---
continuation_contract:
  trigger: artifact_finalized        # | explicit_handoff
  artifact_ref: companies/GLUE/knowledge.md
  artifact_version: "2026-09-08"
  handoff_to: implementation         # logical phase label, not a task ID
---
```

The parent-side contract is informational — the child-side contract is authoritative for validation.

---

## 6. Continuation Contract Schema

### 6.1 Parent-side contract fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `trigger` | string | Yes | `artifact_finalized`, `explicit_handoff`, or `signal` |
| `artifact_ref` | string | Conditionally | Required when `trigger: artifact_finalized`; path or URI to the artifact |
| `artifact_version` | string | Conditionally | Required when `trigger: artifact_finalized`; version identifier |
| `handoff_to` | string | No | Logical phase label (e.g., "implementation"); not a task ID |

### 6.2 Child-side contract fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `triggered_by` | string | Yes | Mirrors parent's `trigger`; must be `artifact_finalized` or `explicit_handoff` |
| `artifact_ref` | string | Conditionally | Required when `triggered_by: artifact_finalized` |
| `artifact_version` | string | Conditionally | Required when `triggered_by: artifact_finalized` |
| `parent_task_id` | string | Yes | The research/design task ID this implementation is derived from |
| `required_artifacts` | list[dict] | No | Explicit list of artifacts that must exist and be finalized; each entry has `path` and `status` fields |

The `required_artifacts` list on the child side is the authoritative artifact checklist. It captures what the implementation task needed at creation time — even if the parent's artifact list changes later. This makes the child task self-contained and auditable.

### 6.3 Parsing

The `continuation_contract` frontmatter is parsed from the task body using the same pattern as the existing `_body_declines_integration_required` parser. The implementer must:

1. Locate the `---`-delimited frontmatter block in the body text.
2. Parse the YAML (or YAML-like) content.
3. Extract the `continuation_contract` dict.
4. Return `None` if no frontmatter block exists or if `continuation_contract` is absent.

The frontmatter is injected/validated by the creation tooling (analogous to how `integration_required` is injected by `create_task()`).

---

## 7. Artifact Validation

### 7.1 The validation hook

The `validate_continuation_artifacts(parent_task, child_task)` function is the central validation primitive. It is called from `recompute_ready()` when considering whether to promote a `todo` child to `ready`, and from a future CLI command `janus kanban validate-continuation <task_id>` for manual verification.

**Return type contract:**

```python
@dataclass
class ValidationResult:
    proceed: bool                    # True = promote to ready; False = stay todo
    blocked_reason: str | None       # Non-None when proceed=False; human-readable
    warnings: list[str]              # Non-blocking notices surfaced in worker context
```

The implementer must ensure `validate_continuation_artifacts()` returns a `ValidationResult`, not a bare bool. The structured return is what allows `recompute_ready` to record the block reason in the task's comment thread and worker context.

### 7.2 When validation runs

Validation runs inside `recompute_ready` (or a `recompute_ready_for_continuation` variant) specifically for child tasks that have a `continuation_contract` with `triggered_by: artifact_finalized`. For `triggered_by: explicit_handoff`, no artifact validation is performed — the parent-done check is sufficient.

The validation is idempotent and re-entrant:
- Reading artifact status is a pure lookup.
- Promotion (`todo` → `ready`) is idempotent — already-`ready` tasks are not re-promoted.
- The `recompute_ready` loop is safe to run multiple times.

### 7.3 Artifact location strategies

Artifacts can live in several places. The validation hook must be able to resolve them:

| Location | Resolution strategy |
|----------|---------------------|
| `companies/<TICKER>/reports/*.md` | Relative path from project root; validated by file existence |
| `companies/<TICKER>/knowledge.md` | Same; validated by file existence + frontmatter status |
| Kanban task body (embedded findings) | Read from the parent task's body; no file resolution needed |
| External URL (web research) | Not validated for existence — recorded as a reference only; implementation task carries the URL |
| Obsidian vault (future) | Resolved via `OBSIDIAN_VAULT_PATH` env; validated by file existence |

The `artifact_ref` field should use a project-relative path when the artifact is a local file, and a URL when it's external.

### 7.4 Required artifacts before promotion

**Trigger A (artifact_finalized):** Before an implementation task can be promoted from `todo` to `ready`, the artifacts referenced in the child's `required_artifacts` list must exist and have `status: finalized`. If any required artifact is missing or not finalized, promotion is blocked.

**Trigger B (explicit_handoff):** No artifact validation is performed. The parent-done check is sufficient.

---

## 8. Phase Transition Diagrams

### 8.1 Trigger A — Artifact-Finalized (primary pipeline)

```
                    ┌──────────────────────────┐
                    │  Research/Design Task     │
                    │  (worktree, integration   │
                    │   Required: false)        │
                    │                          │
                    │  body contains:           │
                    │    continuation_contract: │
                    │      trigger:             │
                    │        artifact_finalized │
                    │      artifact_ref:        │
                    │        companies/GLUE/    │
                    │        knowledge.md       │
                    └────────────┬─────────────┘
                                 │
                    Researcher produces artifact:
                    companies/GLUE/knowledge.md
                    status: draft
                                 │
                    Researcher finalizes
                    artifact: status → finalized
                                 │
                    Researcher completes
                    task → status: done
                                 │
                    ┌────────────▼─────────────┐
                    │  t_impl created with      │
                    │  parents=[t_research]     │
                    │                          │
                    │  body frontmatter:        │
                    │    continuation_contract: │
                    │      triggered_by:        │
                    │        artifact_finalized │
                    │      artifact_ref:        │
                    │        companies/GLUE/    │
                    │        knowledge.md       │
                    │      parent_task_id:      │
                    │        t_research         │
                    │      required_artifacts:  │
                    │        - path: ...        │
                    │          status: finalized│
                    │                          │
                    │  status: todo             │
                    └────────────┬─────────────┘
                                 │
                    recompute_ready runs:
                    1. parent t_research → done ✓
                    2. child has continuation_contract
                    3. trigger = artifact_finalized
                    4. validate_continuation_artifacts()
                       → knowledge.md exists ✓
                       → status: finalized ✓
                    5. proceed = True
                                 │
                    ┌────────────▼─────────────┐
                    │  t_impl → status: ready   │
                    │                          │
                    │  Worker context shows:    │
                    │    ## Continuation        │
                    │    - Trigger:             │
                    │      artifact_finalized   │
                    │    - Artifact:            │
                    │      companies/GLUE/      │
                    │      knowledge.md         │
                    │      (v2026-09-08)        │
                    │    - Parent task:         │
                    │      t_research (done)    │
                    │    - Required artifacts:  │
                    │      knowledge.md —       │
                    │      finalized ✓          │
                    └──────────────────────────┘
```

### 8.2 Trigger B — Explicit Handoff

```
                    ┌──────────────────────────┐
                    │  Design Task              │
                    │  (worktree)               │
                    │                          │
                    │  body contains:           │
                    │    continuation_contract: │
                    │      trigger:             │
                    │        explicit_handoff   │
                    └────────────┬─────────────┘
                                 │
                    Designer completes
                    task → status: done
                                 │
                    ┌────────────▼─────────────┐
                    │  t_impl created with      │
                    │  parents=[t_design]       │
                    │                          │
                    │  body frontmatter:        │
                    │    continuation_contract: │
                    │      triggered_by:        │
                    │        explicit_handoff   │
                    │      parent_task_id:      │
                    │        t_design           │
                    │                          │
                    │  status: todo             │
                    └────────────┬─────────────┘
                                 │
                    recompute_ready runs:
                    1. parent t_design → done ✓
                    2. child has continuation_contract
                    3. trigger = explicit_handoff
                    4. NO artifact validation
                    5. proceed = True
                                 │
                    ┌────────────▼─────────────┐
                    │  t_impl → status: ready   │
                    └──────────────────────────┘
```

### 8.3 Blocked — Missing Artifact

```
                    ┌──────────────────────────┐
                    │  t_research → done        │
                    │  continuation_contract:   │
                    │    artifact_ref:          │
                    │      companies/GLUE/      │
                    │      knowledge.md         │
                    └────────────┬─────────────┘
                                 │
                    t_impl created,
                    status: todo
                                 │
                    recompute_ready runs:
                    1. parent → done ✓
                    2. trigger = artifact_finalized
                    3. validate_continuation_artifacts()
                       → locate_artifact(
                           "companies/GLUE/
                            knowledge.md")
                       → FILE NOT FOUND
                    4. proceed = False
                       blocked_reason:
                       "artifact not found:
                        companies/GLUE/
                        knowledge.md"
                                 │
                    ┌────────────▼─────────────┐
                    │  t_impl stays todo        │
                    │                          │
                    │  Comment thread:          │
                    │    "Continuation blocked: │
                    │     artifact companies/   │
                    │     GLUE/knowledge.md     │
                    │     not found"            │
                    │                          │
                    │  Worker context:          │
                    │    Continuation Contract  │
                    │    section shows:         │
                    │      blocked_reason: ...  │
                    └──────────────────────────┘

                    [Later: researcher creates
                     the file, marks it
                     finalized]

                                 │
                    Next recompute_ready:
                    → knowledge.md found ✓
                    → status: finalized ✓
                    → t_impl → ready
```

### 8.4 Blocked — Artifact Not Finalized

```
                    ┌──────────────────────────┐
                    │  t_research → done        │
                    │  artifact_ref:            │
                    │    companies/GLUE/        │
                    │    knowledge.md           │
                    └────────────┬─────────────┘
                                 │
                    t_impl created,
                    knowledge.md exists
                    but status: draft
                                 │
                    recompute_ready runs:
                    1. parent → done ✓
                    2. trigger = artifact_finalized
                    3. validate_continuation_artifacts()
                       → knowledge.md found ✓
                       → status: draft
                       → expected: finalized
                    4. proceed = False
                       blocked_reason:
                       "artifact not finalized:
                        companies/GLUE/
                        knowledge.md
                        (status='draft',
                         expected finalized)"
                                 │
                    ┌────────────▼─────────────┐
                    │  t_impl stays todo        │
                    │  Block reason recorded    │
                    └──────────────────────────┘

                    [Later: researcher updates
                     knowledge.md frontmatter
                     to status: finalized]

                                 │
                    Next recompute_ready:
                    → status: finalized ✓
                    → t_impl → ready
```

---

## 9. Error Handling

### 9.1 Error classes

| Error class | When it occurs | Behavior | Recovery |
|-------------|----------------|----------|----------|
| `MissingArtifactError` | `artifact_ref` points to a file that doesn't exist | Block continuation; child stays `todo`; error surfaced in task comments + worker context | Researcher/designer must finalize the artifact, or the implementation task must be re-targeted to a different artifact |
| `ArtifactNotFinalizedError` | Artifact exists but `status` is not `finalized` | Block continuation; child stays `todo`; reason: "artifact X is in status Y, expected finalized" | Researcher marks the artifact as `finalized` (via `janus artifact finalize` command or by editing the frontmatter); `recompute_ready` re-evaluates on the next pass |
| `ArtifactVersionMismatchError` | `artifact_version` in the contract doesn't match the actual artifact version | Block continuation; reason: "contract references vX, artifact is vY" | Implementation task's `continuation_contract` is updated to match the actual artifact version, or the artifact is re-finalized at the expected version |
| `NoTriggerDeclaredError` | Child task has no `continuation_contract` and no `parents=` link | Allow promotion via standard parent→child gating (no artifact validation); backward-compatible fallback | None needed — this is the default behavior for tasks without a contract |
| `ParentNotDoneError` | Parent task is not `done` | Standard `recompute_ready` behavior — child stays `todo` | Parent must be completed first |
| `ValidationWarning` (non-blocking) | Artifact exists but has minor issues (e.g., missing sources, low-confidence findings) | Warning surfaced in worker context; continuation proceeds | None — informational only |

### 9.2 Error recovery principles

- **All errors are recoverable.** None are terminal. The task remains `todo` and can be retried after the condition is fixed.
- **No silent degradation.** If validation fails, the reason is explicit and actionable — not a generic "continuation blocked."
- **Failure isolation.** A validation failure for one child does not prevent other children from being promoted. Each child is validated independently in `recompute_ready`.
- **No automatic timeout.** If the artifact is abandoned, the implementation task stays `todo`. A researcher or reviewer can change the trigger to `explicit_handoff` or remove the contract. Automatic timeout would silently skip validation.

### 9.3 Idempotency guarantees

- Reading artifact status is a pure lookup — repeated calls return the same result.
- Promotion (`todo` → `ready`) is idempotent — already-`ready` tasks are not re-promoted.
- The `recompute_ready` loop is safe to run multiple times.
- Completion events can fire multiple times (retries, crash recovery, double-click) — continuation logic must be safe under repeated invocation.

---

## 10. Backward Compatibility

### 10.1 Tasks without a continuation contract

Tasks created before this specification is implemented will not have `continuation_contract` frontmatter. Their behavior is unchanged:

- Parent→child gating works via `recompute_ready` as before.
- No artifact validation is performed (no contract to validate against).
- This is the safe default: existing tasks continue to work exactly as today.

### 10.2 Mixed scenarios

A parent task with a `continuation_contract` can have children without one — e.g., a research task spawns both an implementation child and a documentation child. The implementation child gets the contract; the documentation child uses standard parent→child gating without artifact validation.

### 10.3 Gradual adoption

The `continuation_contract` frontmatter is opt-in. Creators who want artifact-gated continuation add it. Creators who don't (or whose tasks don't have artifacts) omit it. There is no migration of existing tasks required.

### 10.4 Relationship to integration contract

A task can have both `integration_required: true` and a `continuation_contract`. They govern different things:

- `integration_required` governs PR + CI gating on **completion** (the gate at `_enforce_integration_gate()`).
- `continuation_contract` governs artifact-gated promotion from `todo` to `ready` (the `recompute_ready` validation hook).

The two are orthogonal and can coexist.

---

## 11. Acceptance Criteria

These are the verification checklist for any implementation of this specification.

### AC1: Continuation contract frontmatter parsing

- [ ] A Kanban task body can contain a `continuation_contract` frontmatter block with `triggered_by`, `artifact_ref`, `artifact_version`, and `parent_task_id` fields.
- [ ] The frontmatter is parsed correctly from the body text (existing frontmatter parser pattern reused/extended).
- [ ] Missing or malformed frontmatter returns `None` (graceful degradation, not an exception).
- [ ] The parsed contract is visible in `build_worker_context()` output.

### AC2: Artifact-gated promotion (Trigger A)

- [ ] When a child task with `triggered_by: artifact_finalized` has a `done` parent, `recompute_ready` validates that the referenced artifact exists and has `status: finalized`.
- [ ] If validation passes, the child is promoted to `ready`.
- [ ] If validation fails (missing artifact), the child stays `todo` and the reason is recorded in the task's comment thread and worker context.
- [ ] If validation fails (artifact not finalized), the child stays `todo` and the reason is recorded.
- [ ] If validation fails (version mismatch), the child stays `todo` and the reason is recorded.
- [ ] Validation is idempotent and re-runnable.

### AC3: Explicit handoff promotion (Trigger B)

- [ ] When a child task with `triggered_by: explicit_handoff` has a `done` parent, `recompute_ready` promotes it to `ready` without artifact validation.
- [ ] No artifact is required for this trigger type.
- [ ] The promotion happens via the standard parent→child gating path (no new code path for this trigger).

### AC4: `create_continuation_task()` helper

- [ ] A new function creates a child task parented on a research/design task, injecting the `continuation_contract` frontmatter with the provided artifact reference and trigger type.
- [ ] The child task's `required_artifacts` list is populated from the explicit list passed to the function (or from the parent's artifact list if derived).
- [ ] The helper is callable from the CLI creation path, the MCP tool, and any other creation surface.

### AC5: Validation hook

- [ ] `validate_continuation_artifacts(parent_task, child_task)` returns a `ValidationResult` with `proceed`, `blocked_reason`, and `warnings`.
- [ ] The hook is called from `recompute_ready` for tasks that have a `continuation_contract` with `triggered_by: artifact_finalized`.
- [ ] The hook does not affect tasks without a `continuation_contract` (backward compatibility).
- [ ] The hook does not affect tasks with `triggered_by: explicit_handoff` (no artifact validation).

### AC6: Error isolation

- [ ] A validation failure for one child does not prevent other children from being promoted.
- [ ] Validation failures are recorded per-child, not global.

### AC7: Backward compatibility

- [ ] Tasks created without `continuation_contract` frontmatter are promoted by `recompute_ready` exactly as before (standard parent→child gating, no artifact validation).
- [ ] Existing tests for `recompute_ready` and parent→child promotion continue to pass.

### AC8: Worker context visibility

- [ ] A task with a `continuation_contract` shows a "Continuation Contract" section in `build_worker_context()` with trigger type, artifact reference, version, parent task ID, and artifact validation status.
- [ ] The section is absent for tasks without a contract.
- [ ] When blocked, the section shows the `blocked_reason`.

---

## 12. Valid and Invalid Continuation Examples

### 12.1 Valid: Research → Implementation (Trigger A)

```text
1. Research task t_research created (worktree, integration_required: false)
2. Researcher produces companies/GLUE/knowledge.md with status: draft
3. Researcher marks t_research body:
   ---
   continuation_contract:
     trigger: artifact_finalized
     artifact_ref: companies/GLUE/knowledge.md
     artifact_version: "2026-09-08"
   ---
4. Researcher completes t_research → done
5. Artifact finalized: knowledge.md frontmatter updated to status: finalized
6. Implementation task t_impl created with parents=[t_research]:
   ---
   continuation_contract:
     triggered_by: artifact_finalized
     artifact_ref: companies/GLUE/knowledge.md
     artifact_version: "2026-09-08"
     parent_task_id: t_research
     required_artifacts:
       - path: companies/GLUE/knowledge.md
         status: finalized
   ---
7. t_impl status: todo (parent is done, but artifact validation runs)
8. validate_continuation_artifacts() checks knowledge.md → status: finalized ✓
9. t_impl promoted to ready
```

### 12.2 Valid: Design → Implementation (Trigger B)

```text
1. Design task t_design created
2. Designer writes design doc but doesn't finalize a separate artifact
3. Designer marks t_design body:
   ---
   continuation_contract:
     trigger: explicit_handoff
   ---
4. Designer completes t_design → done
5. Implementation task t_impl created with parents=[t_design]:
   ---
   continuation_contract:
     triggered_by: explicit_handoff
     parent_task_id: t_design
   ---
6. validate_continuation_artifacts() sees triggered_by: explicit_handoff
   → no artifact check performed
7. t_impl promoted to ready
```

### 12.3 Invalid: Missing artifact (blocked)

```text
1. t_research done, continuation_contract references
   companies/GLUE/knowledge.md
2. t_impl created with parents=[t_research]
3. validate_continuation_artifacts() checks knowledge.md
   → file not found
4. t_impl stays todo; error:
   "artifact companies/GLUE/knowledge.md not found"
5. Researcher creates the file, marks it finalized
6. Next recompute_ready pass → t_impl promoted to ready
```

### 12.4 Invalid: Artifact not finalized (blocked)

```text
1. t_research done, artifact_ref: companies/GLUE/knowledge.md
2. t_impl created
3. knowledge.md exists but status: draft
4. t_impl stays todo; error:
   "artifact not finalized (status='draft', expected finalized)"
5. Researcher updates knowledge.md frontmatter to status: finalized
6. Next recompute_ready pass → t_impl promoted to ready
```

### 12.5 Invalid: Version mismatch (blocked)

```text
1. t_research done, artifact_ref: companies/GLUE/knowledge.md
   artifact_version: "2026-09-08"
2. t_impl created with artifact_version: "2026-09-08"
3. knowledge.md exists, status: finalized, but version: "2026-09-07"
4. t_impl stays todo; error:
   "artifact version mismatch: contract references v2026-09-08,
    artifact is v2026-09-07"
5. Either: implementation task contract updated to v2026-09-07,
   or artifact re-finalized at v2026-09-08
6. Next recompute_ready pass → t_impl promoted to ready
```

### 12.6 Valid: No contract (backward compatible)

```text
1. Parent task t_parent created without continuation_contract
2. Child task t_child created with parents=[t_parent]
   (no continuation_contract in child body)
3. t_parent → done
4. recompute_ready promotes t_child to ready
   via standard parent→child gating
5. No artifact validation performed
   (no contract to validate against)
```

### 12.7 Invalid: Unknown trigger type (blocked, fail-safe)

```text
1. t_impl created with:
   ---
   continuation_contract:
     triggered_by: unknown_trigger_type
     parent_task_id: t_research
   ---
2. t_research → done
3. should_continue() returns:
   (False, "unknown trigger type: 'unknown_trigger_type'")
4. t_impl stays todo
5. This is the fail-safe behavior — unknown triggers
   are rejected, not silently ignored
```

---

## 13. Implementation Order

The parent design specifies the following implementation order. This specification does not change it.

```text
1. kanban_db.py — add continuation_contract frontmatter parsing
   - Parse continuation_contract from body (reuse existing frontmatter parser pattern)
   - Add validate_continuation_artifacts() function
   - Integrate validation into recompute_ready() for tasks with contracts
   - Add Continuation Contract section to build_worker_context()

2. kanban_db.py — add create_continuation_task() helper
   - Creates child task with continuation_contract frontmatter
   - Parents the child on the research/design task
   - Populates required_artifacts

3. Tests — continuation contract parsing + validation
   - test_parse_continuation_contract_from_body
   - test_validate_continuation_artifacts_artifact_finalized_promotes
   - test_validate_continuation_artifacts_missing_artifact_blocks
   - test_validate_continuation_artifacts_not_finalized_blocks
   - test_validate_continuation_artifacts_version_mismatch_blocks
   - test_validate_continuation_artifacts_explicit_handoff_skips
   - test_recompute_ready_with_continuation_contract
   - test_backward_compat_no_contract_still_promotes
   - test_worker_context_continuation_contract_section
   - test_create_continuation_task_injects_contract

4. CLI (optional, follow-up) — janus kanban validate-continuation <task_id>
   - Manual validation check for a specific task
```

---

## 14. Open Questions (from parent design)

These were deferred to the implementer by the parent design. They are restated here for visibility.

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| OQ1 | Should artifact finalization be a separate lifecycle event, or just a frontmatter status field? | Lifecycle event vs. frontmatter status | Frontmatter status for now. Simpler, no new event infrastructure. Can add lifecycle event later if artifact finalization needs to trigger other reactions. |
| OQ2 | Should `validate_continuation_artifacts` be in `kanban_db.py` or a new module? | Same file vs. new module | New module `kanban_continuation.py` — keeps `kanban_db.py` from growing further. But if it's only a few functions, same file is fine. Defer to implementer. |
| OQ3 | Should the `required_artifacts` list be in the child task body, or derived from the parent? | Child body vs. derived from parent | Child body — makes the child self-contained and auditable. The parent's artifact list can change; the child should capture what it needed at creation time. |
| OQ4 | What happens when a research task is `done` but the artifact is never finalized? | Block forever vs. timeout vs. manual override | Block until resolved. The implementation task stays `todo`. If the artifact is abandoned, the researcher or a reviewer can change the trigger to `explicit_handoff` or remove the contract. No automatic timeout — that would silently skip validation. |

---

## 15. File Index

This specification draws on the following artifacts for context:

| File | Role |
|------|------|
| `reports/task_continuation_design_t_e75fa9e8.md` (in t_e75fa9e8 workspace) | Parent design document — source of the design decisions formalized here |
| `docs/design/connection_model_and_loop_workflow.md` | Adjacent design covering research→goal→action loop; provides context for how continuation fits into the broader loop |
| `docs/specs/research_knowledge_pipeline_specification.md` | Defines the artifact model and `status: finalized` convention that the continuation contract checks |
| `docs/specs/integration_contract.md` | Companion contract governing PR+CI gating on completion; shows the pattern for how a contract frontmatter is structured and consumed |

---

*integration_required: false (design/specification task — no PR needed)*
