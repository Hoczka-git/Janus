# E2E Replenishment Verification — Janus Board

**Date:** 2026-09-06
**Board:** janus
**Project:** p_d550e150 (slug: `janus`)
**Profile:** implementer
**Plugin:** replenishment (enabled in config.yaml)

## Configuration

Three `file` (markdown) planning sources registered in `projects.db`:

| id             | path                     | target_column | max_generated_tasks |
|----------------|--------------------------|---------------|---------------------|
| `roadmap`      | `docs/roadmap.md`        | `triage`      | 1                   |
| `product_backlog` | `docs/product_backlog.md` | `triage`      | 1                   |
| `vision`       | `docs/vision.md`         | `triage`      | 1                   |

All sources use: `format=markdown`, `profiles=["implementer"]`,
`task_title_prefix="[plan]"`.

Project `primary_path` corrected to `/home/dan11hermes/workspaces/janus`
(was pointing to a stale worktree `t_37ecba1b` that no longer contains `docs/`).

## Procedure

1. **Seed task creation**: Created `[plan] E2E replenishment validation seed`
   (id `t_e684ad60`) on the janus board with `project_id=p_d550e150`,
   `assignee=implementer`.

2. **Completion**: Called `kb.complete_task(conn, 't_e684ad60')`, which fired
   the `kanban_task_completed` lifecycle hook → `on_task_completed` →
   `_run_replenishment` → `_replenish`.

3. **Idempotency re-fire**: Re-invoked `on_task_completed('t_e684ad60')` a
   second time to verify no duplicate task generation.

## Results

### Task generation (PASS)

- 1 new task created: `[plan] Implement the structured observability log schema and instrumentation` (id `t_e0a63f9e`).
- Generated task landed in **triage** status (not todo/running).
- `assignee = implementer`.
- Parented on the seed task via `parents=[t_e684ad60]`.

### Cursor advancement (PASS)

- `docs/roadmap.md` line 97 (`- [ ] Implement the structured observability...`)
  was rewritten to `- [x]` after the pull.
- Unchecked TODO count: 1 → 0.

### Audit trail (PASS)

Comment written on seed task `t_e684ad60` by author `replenish`:

```
[replenish] pulled 1 task(s) from 3 source(s) [file:product_backlog, file:roadmap, file:vision] after t_e684ad60 completed
```

### Idempotency (PASS)

- Re-firing `on_task_completed` produced **0 new tasks** (total task count
  unchanged: 201 before → 201 after).
- Audit comment on re-fire:
  ```
  [replenish] pulled 0 task(s) from 3 source(s) [file:product_backlog, file:roadmap, file:vision] after t_e684ad60 completed
  ```
- Three idempotency layers all verified:
  1. **DB idempotency key** (`p_d550e150:roadmap:todo-96`) — prevented duplicate
     INSERT on the same source+line.
  2. **Cursor advancement** — the `[ ]` → `[x]` rewrite means re-parse finds
     no unchecked items.
  3. **Re-entrancy guard** — `_replenishing` set + lock prevented nested
     `_run_replenishment` entry.

### max_generated_tasks (PASS)

- Only 1 task was generated despite 3 sources being configured, confirming the
  global `max_generated_tasks=1` cap is enforced across all sources.

## Conclusion

All acceptance criteria for roadmap-driven replenishment are satisfied:

- [x] Replenishment plugin enabled
- [x] Planning sources registered (roadmap, product_backlog, vision)
- [x] `max_generated_tasks=1` configured (global cap verified)
- [x] `target_column=triage` — generated tasks land in TRIAGE
- [x] E2E validation passed (task generated, parented, audited)
- [x] Idempotency verified (re-fire produces 0 new tasks)
- [x] Audit trail verified (structured `[replenish]` comment with pull count)
