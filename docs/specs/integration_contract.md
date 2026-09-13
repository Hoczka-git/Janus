# Integration Contract — Final Design & Implementation Handoff

**Task:** t_90ca2ff2 — Design automatic integration contract for Kanban tasks
**Status:** Design complete — handoff for follow-up implementation
**Parent results synthesized:** t_67929499 (dispatch map), t_c70019ba (creation mechanism), t_c9c78f0c (field semantics), t_e3f47991 (synthesis proposal)


## 1. What We Now Know

### 1.1 Creation path — single DB entry point

All task creation flows through `kb.create_task()` in `hermes_cli/kanban_db.py:3172`. Four surfaces feed it:

| Surface | File:line | Passes body verbatim? |
|---------|-----------|-----------------------|
| DB function | `kanban_db.py:3172` | Yes — this is the core |
| MCP tool `kanban_create` | `kanban_tools.py:1419` (`_handle_create`) | Yes |
| CLI `hermes kanban create` | `kanban.py:1642` (`_cmd_create`) | Yes |
| Auto-decomposer | `kanban_decompose.py` | Yes — constructs body inline |
| Swarm | `kanban_swarm.py:233` | Yes — constructs body inline |

Right now none of them set `integration_required`. The field only exists as opt-in frontmatter that _must_ be manually written into the body string. The gate at `_enforce_integration_gate()` (`kanban_db.py:5661`) is called by `complete_task()` (`kanban_db.py:5899`) and reads the flag from the body — but nothing guarantees it's there.

### 1.2 The gate — already works, just needs the flag to be guaranteed

`_enforce_integration_gate()` is correct and complete:

1. Non-worktree → returns early (no-op)
2. Worktree + `integration_required: false` in body → skip, emit `completion_integration_skipped`
3. Worktree + flag absent or truthy → query `web_git.review_integration_state()`, pass → verified, fail → `IntegrationGateError`

The gate runs **outside** the completion write transaction — a blocked task leaves zero state mutation. No logic change needed there. The problem is only that the flag is never assigned, so every worktree task silently falls into case 3 (strict) — which is the safe default, but means research/design tasks can't opt out without manually editing the body.

### 1.3 Field semantics — settled

*`integration_required`* is a boolean parsed from body frontmatter:

- **Default:** `true` (gate enforced) — absent flag = strict
- **Falsey:** `false`, `no`, `0`, `off` (case-insensitive)
- **Stored in:** `tasks.body` TEXT — no schema migration
- **Parser** already exists at `kanban_db.py:5431` (`_body_declines_integration_required`)

Classification rule (one question):

> Does this task produce source-code changes that must be PR-merged and CI-verified before `done`?

| Category | Value | Why |
|----------|-------|-----|
| Implementation, bug fix, refactor, tests | `true` (default) | Code change → PR+CI |
| Research, investigation, findings | `false` | Written artifact, no code |
| Design/spec document | `false` | Written artifact |
| Documentation-only | `false` | Markdown, no code behavior change |
| Config/ops (no code gate) | `false` | E.g. `.gitignore`, non-gating CI yaml |
| Orchestration/decomposition | `false` | Creates/coordinates children only |
| Mixed code + docs | `true` (default) | PR covers both |
| Unsure/ambiguous | Omit (default strict) | Safer to block than silently skip |


## 2. The Design — Minimal Implementation

### 2.1 Core change: `create_task()` gets a parameter + resolution

Add `integration_required: Optional[bool] = None` to `create_task()`. When `None` (the common case — all current callers), resolve via heuristic inside the function:

```python
def _resolve_integration_required(
    workspace_kind: str,
    integration_required: Optional[bool],
    body: Optional[str],
) -> bool:
    # 1. Explicit declaration always wins
    if integration_required is not None:
        return integration_required
    # 2. Non-worktree → irrelevant → False
    if workspace_kind != "worktree":
        return False
    # 3. Worktree + body already has flag → use it (backward compat)
    if _body_declines_integration_required(body):
        return False
    # 4. Default-strict: worktree + no declaration → True
    return True
```

Then inject the resolved value into the body before INSERT:

```python
body = _ensure_integration_required_frontmatter(body, resolved_value)
```

`_ensure_integration_required_frontmatter`:
- Body already has the flag → **overwrite** with canonical `integration_required: true/false`
- Body doesn't have it → **prepend** `integration_required: true/false\n`

This makes the body the source of truth with the flag always present and canonical.

The `created` event payload gains `"integration_required": resolved_value` for auditability.

### 2.2 What does NOT need to change

- `_enforce_integration_gate()` — already reads from body, logic is correct
- `complete_task()` — already calls the gate
- The `Task` dataclass — no new field needed; gate reads directly from body
- The schema — no migration; flag lives in body TEXT
- Dispatch — `integration_required` is irrelevant to dispatch; it only affects completion

### 2.3 What SHOULD change (in order)

**Step 1 — DB layer (sufficient alone):**
`kanban_db.py:3172` — add the parameter, `_resolve_integration_required()`, `_ensure_integration_required_frontmatter()`, call both inside the write transaction, add `integration_required` to the `created` event payload.

After this single change, every existing creation surface that passes `integration_required=None` (which is all of them right now) gets automatic heuristic resolution + body injection. The mechanism works end-to-end from day one.

**Step 2 — MCP tool:**
`kanban_tools.py:1419` — add `integration_required` boolean parameter to the `_handle_create` schema, forward it to `kb.create_task()`. Agents can then declare it explicitly instead of fudging the body string.

**Step 3 — CLI:**
`kanban.py:1642` — add `--integration-required` / `--no-integration-required` flags. Pass to `kb.create_task()`.

**Step 4 — Worker context visibility:**
`kanban_db.py:build_worker_context()` — add an "Integration Gate" section after the body block:

```
## Integration Gate
- **integration_required:** true — this task WILL block on a merged PR + green CI.
  Push your branch, open a PR, and ensure CI passes before completing.
```

or

```
## Integration Gate
- **integration_required:** false — this task will NOT block on PR/CI verification.
  Complete when your deliverable is ready.
```

This is the worker-facing complement to the creation-time injection. Currently the worker has no structured way to know what "done" requires.

**Step 5 — Swarm:**
`kanban_swarm.py:233` — set `integration_required=False` explicitly on root, verifier, and synthesizer cards (they produce reviews/syntheses, not code). Leave code-producing worker cards to the heuristic (omit → default-strict).

**Step 6 — Body-edit audit (deferred):**
Any future `UPDATE tasks SET body = ...` path should parse the flag before and after and emit an `integration_required_changed` event if it flipped. Not required for the initial implementation — the current dashboard editors are the only edit surface and flag flips there are rare. This is a safety net for later.


## 3. What Makes This Minimal

- **One function signature change** in the core DB layer propagates to all four creation surfaces automatically (Python default `None` means existing callers are unaffected).
- **No schema migration.** The flag stays in `body` TEXT — the gate already reads from there.
- **No new tables, no new columns, no new indexes.**
- **No dispatch changes.** The field is purely a completion-gate contract.
- **Backward compatible.** Existing tasks without the flag continue to behave as `integration_required: true` — the same as today.
- **The gate itself doesn't change.** `_enforce_integration_gate()` already does the right thing; we're just guaranteeing the flag is always present so the right thing happens predictably.


## 4. Open Questions for the Implementer

These are design decisions the implementation task can resolve without coming back to this root:

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| U1 | Should `kanban_swarm` auto-detect code-producing workers? | Auto-detect vs. leave to heuristic | Leave to heuristic. Swarm children are created via `create_task()` which already resolves `None` correctly. |
| U2 | Body editor flag-flip: block or warn? | Block with confirmation vs. warn event only | Warn event only (`integration_required_changed`). Blocking frustrates legitimate edits. |
| U3 | Gate reads from body (mutable) or `created` event (durable)? | Body vs. event payload | Keep reading from body for now. If body-edit surfaces proliferate, migrate to event-payload reads. The current injection guarantees they match. |
| U4 | Add `integration_required` property to `Task` dataclass? | Yes vs. no | No — low value, no second consumer yet. Add when needed. |
| U5 | MCP tool: auto-infer from assignee profile? | Infer (researcher→False, dev→True) vs. require explicit | Do NOT auto-infer. Require explicit declaration or let the heuristic in `create_task()` handle it. Auto-inference risks misclassification that's hard to debug. |


## 5. Tests Required

The implementation task should add tests for:

1. **`create_task()` with explicit `integration_required=True`** → body contains `integration_required: true`, `created` event has it
2. **`create_task()` with explicit `integration_required=False`** → body contains `integration_required: false`, event has it
3. **`create_task()` with `integration_required=None` + worktree + no body flag** → resolves to `True`, injected into body
4. **`create_task()` with `integration_required=None` + scratch** → resolves to `False`, injected into body
5. **`create_task()` with `integration_required=None` + worktree + body already has `integration_required: false`** → resolves to `False` (body fallback), body canonicalized
6. **Explicit param overrides body flag** — `integration_required=True` with body containing `integration_required: false` → body overwritten to `true`
7. **`build_worker_context()`** renders the Integration Gate section with correct text for both `true` and `false`
8. **Backward compat** — existing tasks without the flag still parse as `true` via `_body_declines_integration_required`
9. **MCP tool** — `kanban_create` with `integration_required` parameter forwards correctly
10. **CLI** — `--integration-required` and `--no-integration-required` flags work


## 6. Implementation Order (Concrete)

```
1. hermes_cli/kanban_db.py
   - Add integration_required: Optional[bool] = None to create_task() signature (line ~3172)
   - Add _resolve_integration_required() helper
   - Add _ensure_integration_required_frontmatter() helper
   - Call resolution + injection inside the write transaction, before INSERT
   - Add "integration_required": resolved_value to the 'created' event payload
   - Add Integration Gate section to build_worker_context() (after body block)

2. tools/kanban_tools.py
   - Add integration_required boolean param to _handle_create schema
   - Forward to kb.create_task()

3. hermes_cli/kanban.py
   - Add --integration-required / --no-integration-required to _cmd_create
   - Pass to kb.create_task()

4. hermes_cli/kanban_swarm.py
   - Set integration_required=False on root/verifier/synthesizer cards

5. Tests (new file or extend existing kanban_db tests):
   - test_create_task_integration_required_explicit_true
   - test_create_task_integration_required_explicit_false
   - test_create_task_integration_required_heuristic_worktree_strict
   - test_create_task_integration_required_heuristic_scratch_false
   - test_create_task_integration_required_body_fallback
   - test_create_task_integration_required_param_overrides_body
   - test_build_worker_context_integration_gate_section
   - test_body_declines_integration_required_backward_compat
   - test_mcp_kanban_create_integration_required_param
   - test_cli_create_integration_required_flags
```


## 7. Handoff Summary

**What this design delivers:** Every Kanban task gets an explicit `integration_required` value at creation time. The value is resolved either from the creator's explicit declaration or from a heuristic (default-strict for worktree tasks, `False` for non-worktree). The resolved value is injected into the task body as canonical frontmatter, emitted in the `created` event for auditability, and surfaced to the worker in their context. The existing integration gate consumes it without any logic changes.

**What the implementer needs to do:** One focused change to `create_task()` in `kanban_db.py` is sufficient to make the mechanism work. Three follow-up changes (MCP tool, CLI, swarm) make the declaration explicit and visible. One more (worker context) makes it visible to the worker. All are additive — no existing behavior is changed or removed.

**What is intentionally out of scope:** Body-edit flag-flip validation (deferred), `Task` dataclass property (deferred), schema migration (not needed), dispatch changes (not needed), gate logic changes (not needed).

**Artifact location:** This document lives in the t_90ca2ff2 workspace at the path below. The four parent artifacts are in their respective worktrees (t_67929499, t_c70019ba, t_c9c78f0c, t_e3f47991) for full traceability.

*integration_required: false (design task — no PR needed)*
