# Findings: Why t_4229930c is Stuck in Triage

**Task:** t_8a521138 — Investigate why t_4229930c is stuck in triage
**Date:** 2026-09-30
**Status:** Complete

---

## Summary

t_4229930c is stuck in triage because it was created via the dashboard with `status: triage`, `assignee: null`, and no specifier has been run against it. The triage column is a **manual-specifier review queue** — tasks sit there until a specifier (human or LLM-powered `kanban_specify`) fleshes out title/body/assignee and promotes them to `todo`. Without an assignee and without a specifier run, the task cannot leave triage.

---

## Root Cause Chain

### 1. Triage is a specifier-review column, not a normal queue

From `hermes_cli/kanban_db.py:3206-3208`:

> "If `triage=True`, status is forced to `triage` regardless of parents — a specifier/triager is expected to promote the task to `todo` once the spec is fleshed out."

The triage column is intentionally a hold queue. Tasks do NOT auto-promote to `ready` or `todo` from triage. The only way out is:

- **Manual:** `hermes kanban specify <task_id>` (CLI) or the equivalent API call
- **Programmatic:** `kanban_db.specify_triage_task()` (called by the specifier)

### 2. The specifier is a separate auxiliary LLM process

`hermes_cli/kanban_specify.py` is the triage specifier — it calls an auxiliary LLM to produce a tightened title, a concrete body (goal/approach/acceptance criteria/out-of-scope), then calls `specify_triage_task()` to flip `triage -> todo`.

The specifier is configured as an auxiliary task in `config.yaml` under `auxiliary.triage_specifier` (see `hermes_cli/main.py:4370`). It is NOT auto-triggered — it runs only when invoked via:

- `hermes kanban specify <task_id>` (single task)
- `hermes kanban specify --all` (all triage tasks)
- Or the dispatcher + web server exposing it as an auxiliary task

### 3. t_4229930c has no assignee and no skills

The task's state:
- `assignee: null` — no profile is assigned
- `status: triage` — stuck in the specifier queue
- `skills: null` — no skills specified (the specifier doesn't target it)
- `workspace_kind: worktree` — it's a project-linked task, but no worktree was created because it never left triage
- `integration_required: true` — it will need a PR + CI gate when it eventually lands in todo/ready

The replenishment plugin's `target_column == "triage"` behavior (see `plugins/replenishment/__init__.py:549`) means **replenished tasks** also land in triage. But t_4229930c was NOT created by replenishment — it was created directly via the dashboard with `status: triage`. The dashboard behavior for triage creation is the same: the task sits in triage waiting for a specifier.

### 4. No specifier has been run against it

There is no event in t_4229930c's history showing a `specify_triage_task` call. The events show only:
- `created` (status: triage)
- `status` (status: triage, requested_status: triage) — three times, all status confirmations

No `kanban specify` invocation, no specifier LLM call, no `triage -> todo` transition.

### 5. Even if specified, the task is enormous

t_4229930c's body contains 13 major audit bullet points covering:
- Documentation/ADR/roadmap/spec audit and cleanup
- Dead code/obsolete compat paths/unused config audit
- Duplicated lifecycle logic consolidation
- CLI command audit
- Kanban task metadata/lifecycle audit
- Test audit
- Config/env vars/feature flags audit
- Scripts/CI tooling audit
- Documentation reference audit
- Repository-wide consistency audit
- Generated artifacts/cache audit
- Error handling/logging audit

This is a **massive** audit task — likely too large for a single worker. It needs to be decomposed into child tasks before it can be executed. The `kanban_decompose` flow (mirrors `kanban_specify` in shape) can fan it out, but decomposition also requires the task to first be in a specify-able state.

---

## Why Other Tasks Aren't Stuck

Tasks like t_f1e900e7 (Phase D) moved through triage successfully because:
1. They were specified (fleshed out with body/assignee)
2. They were assigned to a profile (e.g., implementer, researcher)
3. They were promoted to `todo` → `ready` → dispatched

t_4229930c skipped step 1 — no one specified it.

## The Specifier Gap

The triage specifier (`kanban_specify.py`) requires:
- An auxiliary LLM configured (`auxiliary.triage_specifier` in config.yaml)
- The task to be in `triage` status
- A call to `hermes kanban specify` (CLI) or the web/server API

If the auxiliary LLM is not configured (no provider/model set for `triage_specifier`), `kanban_specify` silently skips — it mirrors `goals.py` behavior: "empty config => skip, don't crash" (see `kanban_specify.py:18-19`). This means even if someone ran `hermes kanban specify --all`, the specifier might do nothing if the aux model isn't configured.

---

## Recommendations

### Immediate (unblocks t_4229930c)

1. **Specify the task:** Run `hermes kanban specify t_4229930c` (or the API equivalent) to flesh out title/body/assignee. This requires `auxiliary.triage_specifier` to be configured in config.yaml.

2. **Or specify manually:** Edit the task via `kanban_db.specify_triage_task()` with a concrete body, title, and assignee. Given the task's scope (13 audit areas), the body should already be detailed enough — it may not need much specifier work.

3. **Assign an assignee:** The task needs a profile (e.g., `researcher` or `reviewer`) to be dispatched.

4. **Decompose before dispatching:** Given the scope, the task should be decomposed into child tasks (one per audit area) via `kanban_decompose` before being promoted to `todo`. The decomposition mirrors the specifier flow: `kanban_decompose.py` calls `specify_triage_task` on the root, then creates children.

### Systemic (prevents recurrence)

5. **Check auxiliary triage_specifier config:** Verify `auxiliary.triage_specifier` has a provider/model configured in `~/.hermes/config.yaml`. If not, the specifier is a no-op and triage tasks pile up.

6. **Dashboard triage creation:** Consider whether the dashboard should require an assignee when creating a triage task, or at least warn that triage tasks need a specifier run before they can be dispatched.

7. **Triage staleness alert:** Consider adding a diagnostic that flags triage tasks older than N days without a `specify_triage_task` event — these are stuck by definition.

---

## Evidence References

- `hermes_cli/kanban_db.py:3172-3208` — `create_task()` triage behavior
- `hermes_cli/kanban_db.py:3483-3484` — triage forces `task_status = "triage"`
- `hermes_cli/kanban_db.py:7826-7905` — `specify_triage_task()` implementation
- `hermes_cli/kanban_specify.py:1-30` — triage specifier module doc + design
- `hermes_cli/kanban_decompose.py:12-21` — decomposition mirrors specifier shape
- `plugins/replenishment/__init__.py:549` — `target_column == "triage"` in replenishment
- `docs/guides/replenishment_tasks.md:38, 227` — docs describe triage as "specifier review"
- `docs/guides/replenishment_sources.md:106` — `target_column` docs
- `hermes_cli/main.py:4370` — `triage_specifier` auxiliary task registration
