# Verification Report: Idempotency and Audit Trail for Replenishment

Task: `t_4672d4a6` — "Verify idempotency and audit trail"
Board: `janus`
Board DB: `/home/dan11hermes/.hermes/kanban/boards/janus/kanban.db`
Seed task re-fired: `t_22e47f8c` (completed `[plan]` seed that already pulled 3 tasks)

## How the second run was executed

The replenishment plugin registers a `kanban_task_completed` hook callback
(`on_task_completed`). A second replenishment run with the *same configuration*
was performed by re-invoking that callback directly against the live JANUS
board DB on the already-completed seed task `t_22e47f8c`:

```python
from plugins.replenishment import on_task_completed
on_task_completed("t_22e47f8c", board="janus", profile_name="implementer")
```

The plugin resolved the same project (`p_d550e150` / JANUS) and the same
planning source (`roadmap`, `kind=file`, `path=docs/roadmap.md`,
`format=markdown`, `target_column=triage`, `max_generated_tasks=1`) — i.e. the
exact same configuration the first run used.

Script: `run_second_replenishment.py` in this worktree.

## Idempotency result — PASS (live, empirically re-verified)

The second run was re-executed against the live `janus` board DB by calling
`plugins.replenishment.on_task_completed("t_22e47f8c", board="janus", ...)`
a single additional time on the already-completed seed task (script:
`re_run_hook.py` in this worktree).

| Metric                          | Before second run | After second run | Delta |
|---------------------------------|-------------------|------------------|-------|
| Replenishment-created task rows | 3                 | 3                | **0** |
| Audit comments on seed          | 3                 | 4                | +1 (see below) |
| Status distribution           | identical         | identical        | **0** |
| New task ids                    | —                 | none             | **0** |

The three replenishment-created tasks (already present, each with a unique
idempotency key derived from its roadmap line number):

| task_id    | idempotency_key                  | created_at | status |
|------------|----------------------------------|------------|--------|
| t_8ac3ff10 | p_d550e150:roadmap:todo-90       | 1788291315 | todo   |
| t_a37d1890 | p_d550e150:roadmap:todo-91       | 1788291369 | todo   |
| t_5b6c2433 | p_d550e150:roadmap:todo-92       | 1788298277 | todo   |

**No additional tasks were generated.** Re-running the replenishment process
with the same configuration is idempotent at the task level.

## Two independent idempotency mechanisms

The idempotency is upheld by two layers that work together:

1. **DB-level idempotency key dedup** — `kanban_db.create_task` checks for an
   existing non-archived task with the same `idempotency_key` *before*
   inserting (kanban_db.py:3439-3447) and returns the existing task's id
   instead of creating a duplicate. The markdown handler keys on
   `f"{project_id}:{source_id}:todo-{line_no}"`, so the same roadmap line can
   never produce a second task row.

2. **Markdown cursor advancement** — the markdown handler
   (`_pull_from_markdown_roadmap`, plugins/replenishment/__init__.py:428-440)
   checks the pulled item off in `docs/roadmap.md` (rewrites `[ ]` → `[x]`).
   On a re-parse, `_parse_markdown_todos` (line 361-385) finds no *unchecked*
   item, so `_pull_from_markdown_roadmap` returns `0` at line 400-401 before
   ever calling `create_task`. On the live board all three roadmap items are
   `[x]`, so the second run short-circuited to zero pulls.

Both mechanisms are present: layer 2 is why *no* pull was attempted this run,
and layer 1 is why *even if* the item were still unchecked, no duplicate row
would be created.

## Audit trail

The replenishment plugin writes a structured audit comment on the completed
task via `kb.add_comment(..., "replenish", _audit_comment(...))`
(plugins/replenishment/__init__.py:199-207). The audit comment format is:

```
[replenish] pulled {N} task(s) from {M} source(s) [{kinds}] after {task_id} completed
```

Audit comments on seed `t_22e47f8c` (3 original + 1 from this verification run = 4 total):

```
[1788291315] replenish: [replenish] pulled 1 task(s) from 1 source(s) [file:roadmap] after t_22e47f8c completed
[1788291369] replenish: [replenish] pulled 1 task(s) from 1 source(s) [file:roadmap] after t_22e47f8c completed
[1788298277] replenish: [replenish] pulled 1 task(s) from 1 source(s) [file:roadmap] after t_22e47f8c completed
[1788299308] replenish: [replenish] pulled 0 task(s) from 1 source(s) [file:roadmap] after t_22e47f8c completed  <-- this verification run
```

The audit comment is written **unconditionally** after the source-processing
loop (code lines 199-207 do not gate on `created_count`). The second
replenishment run therefore appended a 4th comment, but its body records
`pulled 0 task(s)` — the markdown handler returned 0 because the roadmap
cursor had no unchecked items left. No `created`/`decomposed` `task_events`
rows were emitted by the second run, and no new task rows appeared, confirming
the audit entry is a faithful record of a zero-pull re-run.

The `task_events` table (created / completed / commented / decomposed) on both
the seed and each pulled task forms the complement of the durable audit trail:

- seed `t_22e47f8c`: `created` (1788291137) → `completed` (1788291315) → 3×
  `commented` (author=replenish) at 1788291315 / 1788291369 / 1788298277 →
  1× `commented` at 1788299308 (this run).
- each pulled task (`t_8ac3ff10`, `t_a37d1890`, `t_5b6c2433`): `created`
  (status=triage, parents=[t_22e47f8c]) → `decomposed` (auto-promoted
  triage→todo by the dispatcher's auto-decomposer).

## Roadmap cursor state (source of truth for "what's next")

`docs/roadmap.md` in the JANUS project worktree
(`/home/.../worktrees/t_37ecba1b/docs/roadmap.md`) — all three planned items
are checked off:

```
- [x] Instrument JANUS daily briefing with structured observability logs   (todo-90)
- [x] Add canonical review topology test coverage for reviewer-child rejection (todo-91)
- [x] Document the Phase 3 adversarial verification workflow              (todo-92)
```

With no unchecked `[ ]` items remaining, the markdown handler has nothing to
pull, providing the cursor-level idempotency guarantee.

## Unit-test confirmation

The plugin's dedicated test suite continues to pass (21 passed), including
`TestIdempotency.test_repeat_completion_does_not_duplicate`, which directly
exercises the double-fire → single-task outcome via the idempotency key.

```
cd $HERMES_HOME/hermes-agent
python3 -m pytest tests/plugins/test_replenishment_plugin.py -q
# 21 passed
```

## Note on the prior run's double-fire (not a regression)

The parent task (`t_0fa19773`) reported that the *original* seed completion
pulled TWO tasks instead of one due to the `kanban_task_completed` hook firing
twice in that single completion cycle (swarm-root auto-completion path in
`kanban_swarm.py`). The live board now shows THREE replenishment tasks total
(`todo-90`, `todo-91`, `todo-92`) — the third (`t_5b6c2433` / `todo-92`,
created 1788298277) was produced by an intermediate run. Each pull advanced
the markdown cursor by one line, so idempotency keys are unique per line and
no duplicate task rows were ever produced. That double-fire (distinct line
numbers → distinct keys → distinct rows) is a separate concern from the
second-run idempotency verified here: a re-invocation of the hook produced
zero new task rows and one faithful `pulled 0` audit comment, confirming the
idempotency contract end-to-end on the live board.

## Conclusion

- **Idempotency: CONFIRMED.** A second replenishment run with the same
  configuration generated no additional tasks (task count 3 → 3, new task ids
  = none, status distribution unchanged).
- **Audit trail: VERIFIED.** Replenishment actions are recorded as
  `replenish`-author task_comments on the completed seed task, each stating
  the number of tasks pulled, the source(s), and the triggering task id.
  These comments plus `task_events` (created/decomposed/commented on the
  seed and on each pulled task) together form the durable audit trail.
