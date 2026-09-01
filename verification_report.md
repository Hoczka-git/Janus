# Verification Report: JANUS TRIAGE Task After Replenishment Run

## Task: t_0fa19773 — "Verify exactly one appropriate task in JANUS TRIAGE"

## Executive Summary

**No — exactly one task does NOT appear in JANUS TRIAGE.** Zero tasks currently
appear in the triage column. The replenishment run on the JANUS board pulled **two**
tasks (not one) from the roadmap, and both were immediately auto-decomposed from
`triage` to `todo` by the dispatcher's auto-decomposer.

## Evidence (from kanban.db queries)

### 1. Current status distribution
| status   | count |
|----------|-------|
| archived | 53    |
| done     | 12    |
| ready    | 4     |
| running  | 3     |
| todo     | 13    |
| **triage** | **0** |

**Zero tasks have `status="triage"`.** The JANUS TRIAGE column is empty.

### 2. Tasks created by the replenishment run
Two tasks were created by the replenishment hook (identified by
`idempotency_key LIKE 'p_d550e150:roadmap:%'`):

| task_id      | title                                           | initial status | current status | idempotency_key                  |
|--------------|-------------------------------------------------|----------------|----------------|----------------------------------|
| t_8ac3ff10   | [plan] Instrument JANUS daily briefing...       | triage         | **todo**       | p_d550e150:roadmap:todo-90       |
| t_a37d1890   | [plan] Add canonical review topology test...   | triage         | **todo**       | p_d550e150:roadmap:todo-91       |

Both were created with `status="triage"` (per `target_column=triage` config,
replenishment plugin line 425: `triage=cfg.get("target_column") == "triage"`).

### 3. Auto-decomposition timeline

Both tasks were immediately auto-decomposed by the dispatcher:

**t_8ac3ff10**:
- [1788291315] `created` — status=triage
- [1788291350] `decomposed` — decomposed into [t_8da8ead6, t_abd4c594, t_e4e2d018, t_d22c0394], root flipped triage→todo

**t_a37d1890**:
- [1788291369] `created` — status=triage
- [1788291417] `decomposed` — decomposed into [t_35e6f109, t_17c567d3], root flipped triage→todo

### 4. Why two tasks were pulled instead of one

The config has `max_generated_tasks=1`, but the markdown handler
(`_pull_from_markdown_roadmap`, line 442) **always pulls exactly one item per
invocation** and does not consult `max_generated_tasks`. The hook fired
**twice** for a single completion of seed task `t_22e47f8c`:

- Seed `t_22e47f8c` completed once at [1788291315] (one `completed` event,
  one `task_run`)
- Replenishment comment #1 at [1788291315] (immediate, from `complete_task`)
- Replenishment comment #2 at [1788291369] (54 seconds later)

The in-process re-entrancy guard (`_replenishing` set in the plugin) does not
prevent the double-fire because the `kanban_task_completed` hook is fired
synchronously in-process by `complete_task()` → `_fire_kanban_lifecycle_hook()`
→ `plugins.invoke_hook()` → `on_task_completed()`. The double-fire appears to
come from the seed being processed by a swarm root whose activation also
fires `kanban_task_completed` (see `kanban_swarm.py` line 188-195).

### 5. Roadmap cursor advancement

The roadmap (`docs/roadmap.md`) cursor advanced correctly — two items were
checked off (matching the two pulled tasks):

```
- [x] Instrument JANUS daily briefing with structured observability logs
- [x] Add canonical review topology test coverage for reviewer-child rejection
- [ ] Document the Phase 3 adversarial verification workflow
```

### 6. Audit trail

Two audit comments were left on the seed task `t_22e47f8c` by the
`replenish` author:
```
[replenish] pulled 1 task(s) from 1 source(s) [file:roadmap] after t_22e47f8c completed
[replenish] pulled 1 task(s) from 1 source(s) [file:roadmap] after t_22e47f8c completed
```

Both parented on the seed `t_22e47f8c`; idempotency keys are unique (no
duplicates).

## Root Cause Analysis

1. **Double hook fire**: The `kanban_task_completed` hook fires twice for the
   seed task — once from `complete_task()` and once from the swarm root
   auto-completion path (`kanban_swarm.py:188`). The in-process `_replenishing`
   re-entrancy guard is ineffective because each hook invocation is a fresh
   call path; the guard only prevents nested calls *within* a single invocation.

2. **`max_generated_tasks` not enforced**: The markdown roadmap handler does
   not read `max_generated_tasks` from config — it always returns `1` per call
   (line 442). If the config were respected, the handler would need to be
   aware of an upper bound across invocations (stateful), or the hook would
   need to be made idempotent at the DB level via idempotency keys (which it
   partially is, but each pull gets a distinct `item_id`).

3. **Auto-decomposition removes tasks from triage**: The JANUS board has
   `auto_decompose=True` (default). As soon as a worktree-backed task lands in
   `triage`, the dispatcher's auto-decomposer fan-outs it into children and
   flips the root to `todo` — so tasks never persist in `triage` unless the
   auto-decomposer is disabled or the task lacks a workspace.
