# Integration Required Policy Specification

**Status:** Final — authoritative spec for implementation
**Last verified:** 2026-09-30
**Scope:** Determines when a task's completion is gated on a merged PR + green CI.

This document defines the complete `integration_required` policy: explicit metadata precedence, deterministic type-based auto-detection, ambiguous fallback, non-worktree handling, and parent/child independence semantics. It serves as the single source of truth for implementers working in `kanban_db.py`, the Hermes CLI, and any Janus-side surfaces that create tasks.

---

## 1. Field Definition

`integration_required` is a boolean frontmatter flag stored in `tasks.body` TEXT. It controls whether the integration gate (`_enforce_integration_gate()`) blocks task completion on a merged PR + green CI.

| State | Gate behavior |
|-------|---------------|
| `true` (explicit or default) | Gate enforced: worktree task cannot complete without merged PR + CI |
| `false` (explicit) | Gate skipped: completion proceeds immediately, emits `completion_integration_skipped` |
| Absent | Deferred to resolution heuristic (see §3) |

**Classification question:**

> Does this task produce source-code changes that must be PR-merged and CI-verified before `done`?

| Task category | Recommended value | Rationale |
|---------------|-------------------|-----------|
| Implementation, bug fix, refactor, tests | `true` | Code change → PR + CI |
| Research, investigation, findings | `false` | Written artifact, no code |
| Design/spec document | `false` | Written artifact |
| Documentation-only | `false` | Markdown, no behavior change |
| Config/ops (no code gate) | `false` | E.g. `.gitignore`, non-gating CI yaml |
| Orchestration/decomposition | `false` | Creates/coordinates children only |
| Mixed code + docs | `true` | PR covers both |
| Unsure/ambiguous | Omit (default strict) | Safer to block than silently skip |

---

## 2. Explicit Metadata Precedence

When `integration_required` is explicitly provided as a creation parameter — whether by the Hermes CLI, MCP tool, auto-decomposer, swarm orchestrator, or any Janus creation surface — that value is **always sovereign** and cannot be overridden by any heuristic.

**Resolution order:**

1. **Explicit parameter wins.** If `integration_required` is `True` or `False` at creation time, use it directly. No further inspection occurs.
2. Body frontmatter in the task body string is **overwritten** with the canonical resolved value, so the stored body always reflects what was resolved — never a stale manually-injected flag.
3. The resolved value is emitted on the `created` event for auditability.

**Implementation note:** This is the first step in `_resolve_integration_required()`. Once an explicit value is present, the function returns immediately. The body injection function `_ensure_integration_required_frontmatter()` then canonicalises it into the body (lowercase `true`/`false`, prepended or overwritten in place).

**Why this matters:** A creator that passes `integration_required=False` to a worktree research task gets `False` even though the workspace-kind default would be `True`. Conversely, a creator that passes `integration_required=True` to a scratch task gets `True` even though the non-worktree default is `False` — though the gate will still be a no-op for scratch workspaces (see §4).

---

## 3. Deterministic Type-Based Auto-Detection

When `integration_required` is **not** explicitly provided (the common case — all current callers omit it), the resolution heuristic runs. The current implementation uses workspace-kind only. Type-based auto-detection **augments** (not replaces) the workspace-kind heuristic.

### 3.1 Two-phase resolution

**Phase 1 — workspace-kind guard (existing, unchanged):**

- If `workspace_kind != "worktree"` → return `False`. The gate is a no-op for scratch/dir workspaces with no git branch, so the flag is irrelevant.

**Phase 2 — type-based detection (new):**

For worktree tasks with no explicit declaration, inspect the task **title** and **body** for type signals. The detection runs after the workspace-kind guard, so non-worktree tasks never reach it.

### 3.2 Type signal taxonomy

Signals are checked in priority order. The first matching category determines the result.

#### A. Explicit body frontmatter (highest priority, already implemented)

If the body already contains `integration_required: false` (or `no`/`0`/`off`), return `False`. This preserves backward compatibility with tasks that hand-inject the flag before the heuristic existed. If the body contains `integration_required: true`, return `True`.

#### B. Title keywords

Scan the title (case-insensitive) for category markers:

| Signal | Result | Examples |
|--------|--------|----------|
| `research`, `investigate`, `find`, `study`, `audit`, `review` (as noun) | `False` | "Research integration_required usage", "Audit stale followups" |
| `design`, `spec`, `specification`, `architecture` | `False` | "Design integration contract", "Spec Phase G scope" |
| `document`, `write`, `draft`, `drafting` | `False` | "Document finalized policy" |
| `plan`, `roadmap`, `backlog` | `False` | "Plan Phase E", "Update roadmap" |
| `decompose`, `break down`, `fan out` | `False` | "Decompose epic into tasks" |
| `implement`, `fix`, `refactor`, `build`, `add`, `create`, `ship` (with code context) | `True` | "Implement integration gate", "Fix bug in parser" |
| `test`, `write tests`, `add tests` | `True` | "Add tests for kanban_db" |
| `update`, `modify`, `change` (ambiguous) | Omit (fall through) | "Update docs" — could be doc or code |

#### C. Body heuristics (when title is ambiguous)

If the title doesn't match a clear category, inspect the body text:

- Body contains file paths ending in `.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, `.c`, `.cpp`, `.rb`, `.php` with accompanying "implement/fix/add/change" language → `True`
- Body is predominantly prose with no code-file references and no implementation verbs → `False`
- Body references "PR", "merge", "CI", "review" in a code-change context → `True`
- Body is a literature review, data analysis, findings report, meeting notes → `False`

#### D. Explicit role markers (if a `task_role` or similar field exists in the future)

If a task carries an explicit role classification in body frontmatter (e.g. `task_role: research`, `task_role: implementation`), use it directly. This is forward-compatible and does not conflict with the existing `integration_required` frontmatter.

### 3.3 Precedence within type detection

Order of evaluation:

1. Explicit body frontmatter (`integration_required: ...` line) → use it
2. Title keyword match → use it
3. Body heuristic match → use it
4. No match → fall through to ambiguous fallback (§5)

Each signal category is evaluated independently; the first conclusive match wins. A title keyword match short-circuits body inspection.

### 3.4 Implementation shape

```python
def _detect_integration_required_from_type(title: str, body: Optional[str]) -> Optional[bool]:
    """Return True/False when type signals are conclusive, None when ambiguous."""
    title_l = title.lower()
    # Title keywords → False (research/design/doc)
    if any(kw in title_l for kw in ("research", "investigate", "find", "study",
                                      "audit", "design", "spec", "specification",
                                      "architecture", "document", "write", "draft",
                                      "plan", "roadmap", "backlog", "decompose")):
        return False
    # Title keywords → True (implementation)
    if any(kw in title_l for kw in ("implement", "fix", "refactor", "build",
                                      "add", "create", "ship", "test", "write tests")):
        return True
    # Body heuristics (only when title is ambiguous)
    if body:
        body_l = body.lower()
        # Code-file references + implementation verbs → True
        if re.search(r"\.(py|js|ts|go|rs|java|c(pp)?|rb|php)\b", body_l):
            if any(v in body_l for v in ("implement", "fix", "add", "change", "build")):
                return True
        # Predominantly prose, no code signals → False
        if not re.search(r"\.(py|js|ts|go|rs|java|c(pp)?|rb|php)\b", body_l):
            if any(v in body_l for v in ("findings", "review", "analysis", "report",
                                          "notes", "literature", "survey")):
                return False
    return None  # ambiguous
```

This function is called **after** the workspace-kind guard and **after** the explicit-parameter check. It returns `None` when inconclusive, which triggers the ambiguous fallback.

---

## 4. Non-Worktree Handling Semantics

### 4.1 Rule

Any task with `workspace_kind` of `scratch` or `dir` resolves `integration_required` to `False`, regardless of explicit parameter or type signals.

### 4.2 Rationale

The integration gate (`_enforce_integration_gate()`) is a no-op for non-worktree tasks:

1. It checks `workspace_kind != "worktree"` first and returns early.
2. Scratch/dir workspaces have no git branch, so there is no PR to merge and no CI to verify.
3. The gate would be meaningless; setting the flag to `False` makes this explicit and avoids confusion.

### 4.3 Interaction with explicit declarations

An explicit `integration_required=True` on a scratch task **still resolves to `False`** because the workspace-kind guard runs first in the resolution order. This is intentional: the gate cannot function without a branch, so the flag is irrelevant. The explicit parameter is recorded in the `created` event for auditability, but the stored body flag is canonicalised to `false`.

**Implementation note:** The workspace-kind guard is step 2 in `_resolve_integration_required()`, before the type-detection phase. This ordering is deliberate — non-worktree is a hard override that no type signal can defeat.

### 4.4 Consistency across surfaces

The `workspace_kind != "worktree"` guard appears in:

- `_enforce_integration_gate()` — the gate itself
- `_resolve_integration_required()` — the creation-time heuristic
- Swarm root/verifier/synthesizer creation — these pass `integration_required=False` explicitly but would also resolve to `False` via the guard
- Replenishment plugin — passes `integration_required=False` explicitly

All surfaces are consistent. No surface should bypass the guard.

---

## 5. Safe Ambiguous Fallback Behavior

When type-based detection returns `None` (no conclusive signal), the resolution falls back to the **workspace-kind default**:

- **Worktree + ambiguous type** → `True` (default-strict)
- **Non-worktree + ambiguous type** → `False` (already handled by §4)

### 5.1 Why default-strict for ambiguous worktree tasks

An ambiguous worktree task could be either code-producing or not. The safe default is to **enforce the gate** (block on PR + CI) rather than silently skip it:

- A blocked task is visible on the board — the creator can see the gate is waiting and adjust.
- A silently-skipped gate hides the fact that integration was not verified.
- It is easier to manually set `integration_required=False` on a task that turned out to be non-code than to realise later that a code task was never CI-verified.

### 5.2 How to escape the fallback

The creator can always disambiguate by:

1. Passing an explicit `integration_required=True/False` at creation time.
2. Editing the body to add `integration_required: false` frontmatter before dispatch (the body frontmatter check in §3.2A will catch it).
3. Choosing a task title that contains a clear type keyword.

### 5.3 What the fallback is NOT

- It is **not** a guess. The heuristic deliberately returns `None` rather than picking a side when signals are mixed or absent.
- It is **not** inherited from the parent task. See §6.
- It is **not** deferred to dispatch time. The flag is resolved and injected into the body at creation time, so the task carries a definitive value from the start.

---

## 6. Independent Parent/Child Semantics

### 6.1 Rule

Each task — parent or child — resolves its own `integration_required` **independently** at creation time. There is **no inheritance**, **no propagation**, and **no override** from parent to child or vice versa.

### 6.2 What this means in practice

| Scenario | Child's integration_required |
|----------|------------------------------|
| Parent is `true`, child is a research task | Child resolves to `False` (type detection or explicit) |
| Parent is `false`, child is an implementation task | Child resolves to `True` (default-strict or explicit) |
| Parent has no flag, child has explicit `False` | Child is `False` — explicit wins |
| Parent has no flag, child has no signal | Child resolves via heuristic independently |

### 6.3 Why independence

- **Different tasks have different content.** A decomposition parent that breaks an epic into children is orchestration (no code gate), but one of its children may be a code implementation (needs a gate). Inheritance would be wrong for at least one of them.
- **Different creation paths.** Parents and children may be created by different surfaces (decomposer, swarm, manual CLI) with different information available at creation time. Each surface should resolve based on what it knows about that specific task.
- **No transitive gating.** The integration gate applies to the completing task only. A parent's gate status does not affect a child's gate, and a child's gate does not affect the parent's. The two are orthogonal:
  - `integration_required` governs **completion** (the PR+CI gate on `done`).
  - Parent/child topology governs **todo→ready promotion** (via `_landing_status_after_parents()` + `recompute_ready()`).

### 6.4 Interaction with decomposition

When the auto-decomposer creates child tasks from a parent body, each child is inserted with its own `integration_required` resolution:

1. The decomposer calls `create_task()` (or equivalent INSERT) for each child.
2. Each child's `integration_required` is resolved using that child's own `workspace_kind`, explicit parameter (if any), and body/title signals.
3. The parent's `integration_required` is never consulted during child resolution.

This is already the behavior in the decomposition code path (`kanban_db.py` ~8060): `ir_value = _resolve_integration_required(child_ws_kind, child.get("integration_required"), body)` — the child's own parameters are passed, not the parent's.

### 6.5 Swarm roots

Swarm root, verifier, and synthesizer tasks are a special case of independence:

- Swarm roots are orchestration/planning tasks that create children but do not produce code themselves. They carry `integration_required=False` explicitly.
- Verifier and synthesizer tasks also carry `integration_required=False`.
- These are explicit declarations, not derived from any parent (they have none). They are sovereign for their own tasks only.

---

## 7. Interaction with Continuation Contract

The `continuation_contract` frontmatter is a separate mechanism that governs **todo→ready promotion** semantics (whether a child waits for its parent to complete before becoming ready). It is NOT an alternative to `integration_required`.

| Mechanism | Governs | Stored in |
|-----------|---------|-----------|
| `integration_required` | Completion gate (PR + CI on `done`) | `tasks.body` frontmatter |
| `continuation_contract` | Todo→ready promotion (parent completion dependency) | `tasks.body` frontmatter |

A task can have both. They are orthogonal and do not interact:

- A research task (`integration_required=False`) can still have a `continuation_contract` if it should wait for a parent.
- An implementation task (`integration_required=True`) can have no `continuation_contract` if it is independent of its parent.

This separation is intentional and must be preserved in any policy interpretation. Do not conflate the two.

---

## 8. What Is Out of Scope

The following are explicitly deferred and are not part of this policy:

1. **Body-edit flag-flip handling.** If a worker edits a task body to change `integration_required: true` to `false` (or vice versa) after creation, the stored flag changes but the creation-time resolution is not re-run. This is acceptable — the body flag is the source of truth for the gate at completion time. Re-resolution at edit time is a separate concern.

2. **Worker context Integration Gate section.** The Hermes worker context currently does not surface the `integration_required` value or gate status to the worker. This is a documentation/UX concern, not a policy concern.

3. **Janus-side integration of the field.** The `integration_required` field is a Hermes-side concern that wraps the Janus completion path. Janus creation surfaces (replenishment plugin, etc.) pass `integration_required=False` explicitly or omit it. Integrating type-based detection into Janus creation surfaces is a separate implementation task.

4. **Task role field.** A first-class `task_role` field (research, implementation, design, etc.) would simplify type detection but is not required. The keyword-based heuristic in §3.2 works without it.

5. **E2E verification of the policy.** Verifying that the policy works end-to-end across real task creation, dispatch, completion, and gate enforcement is a separate validation task.

---

## 9. Resolution Algorithm Summary

```
_resolve_integration_required(workspace_kind, integration_required_param, body, title) → bool:

1. If integration_required_param is not None:
       return integration_required_param            # explicit wins

2. If workspace_kind != "worktree":
       return False                                  # non-worktree → irrelevant

3. If body has integration_required: false|no|0|off:
       return False                                  # body frontmatter decline

4. type_result = _detect_integration_required_from_type(title, body)
   If type_result is not None:
       return type_result                            # type-based detection conclusive

5. return True                                       # worktree + ambiguous → default-strict
```

After resolution, `_ensure_integration_required_frontmatter(body, resolved_value)` canonicalises the value into the body before INSERT.

---

## 10. Verification Checklist

For any implementation of this policy, verify:

- [ ] Explicit `True`/`False` parameter always wins, even when body contradicts it
- [ ] Non-worktree (`scratch`, `dir`) always resolves to `False` regardless of other signals
- [ ] Worktree + no explicit param + no body flag + ambiguous type → `True` (default-strict)
- [ ] Worktree + no explicit param + body flag `false` → `False` (backward compat)
- [ ] Title keyword research/design/doc → `False`
- [ ] Title keyword implement/fix/test → `True`
- [ ] Body code-file reference + implementation verb → `True`
- [ ] Body prose-only findings/report → `False`
- [ ] Mixed/unclear signals → `None` → falls back to default-strict (worktree) or `False` (non-worktree)
- [ ] Parent `integration_required` never consulted when resolving child
- [ ] Child `integration_required` never propagates to parent
- [ ] Decomposition creates each child with independent resolution
- [ ] Swarm root/verifier/synthesizer carry `False` explicitly
- [ ] `continuation_contract` and `integration_required` coexist without interaction
- [ ] Resolved value is canonicalised into body before INSERT
- [ ] Resolved value emitted on `created` event for auditability
- [ ] Gate at `_enforce_integration_gate()` unchanged — only the flag source is new

---

## 11. Related Documents

- `docs/implementation_notes/t_0bbdd981_integration_required.md` — Hermes-side implementation reference (PR #16, commit dee3506d2)
- `docs/specs/integration_contract.md` — Design for automatic integration contract
- `docs/design/task_continuation_semantics_spec.md` — Continuation contract spec (orthogonal mechanism)
- `docs/roadmap.md` — Roadmap item #168 (this policy's origin)
- `docs/guides/replenishment_tasks.md` — Replenishment plugin usage of `integration_required=False`
