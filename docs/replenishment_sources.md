# Replenishment Planning Sources

## Overview

The JANUS project uses the Hermes **replenishment** plugin to automatically
pull tasks from configured planning sources when a `[plan]`-prefixed task
completes. The plugin hooks into the `kanban_task_completed` lifecycle event,
resolves the project, loads planning sources from `projects.db`, and creates
new board tasks from the next items in each source.

## Configuration Location

Planning sources are stored in the per-profile projects database:

```
~/.hermes/profiles/implementer/projects.db
```

Table: `planning_sources`

The JANUS project record:
- **id**: `p_d550e150`
- **slug**: `janus`
|- **primary_path**: `/home/dan11hermes/workspaces/janus`
- **board_slug**: `default`

## Configured Planning Sources

### 1. Janus Roadmap (file source)

| Field       | Value                                       |
|-------------|---------------------------------------------|
| id          | `roadmap`                                   |
| kind        | `file`                                      |
| name        | Janus Roadmap                               |
| priority    | 0                                           |
| enabled     | true                                        |

**Config JSON:**

```json
{
  "path": "docs/roadmap.md",
  "format": "markdown",
  "profiles": ["implementer"],
  "task_title_prefix": "[plan]",
  "target_column": "triage",
  "max_generated_tasks": 1
}
```

### 2. Janus Product Backlog (file source)

| Field       | Value                                       |
|-------------|---------------------------------------------|
| id          | `product_backlog`                           |
| kind        | `file`                                      |
| name        | Janus Product Backlog                       |
| priority    | 0                                           |
| enabled     | true                                        |

**Config JSON:**

```json
{
  "path": "docs/product_backlog.md",
  "format": "markdown",
  "profiles": ["implementer"],
  "task_title_prefix": "[plan]",
  "target_column": "triage",
  "max_generated_tasks": 1
}
```

### 3. Janus Vision (file source)

| Field       | Value                                       |
|-------------|---------------------------------------------|
| id          | `vision`                                    |
| kind        | `file`                                      |
| name        | Janus Vision                                |
| priority    | 0                                           |
| enabled     | true                                        |

**Config JSON:**

```json
{
  "path": "docs/vision.md",
  "format": "markdown",
  "profiles": ["implementer"],
  "task_title_prefix": "[plan]",
  "target_column": "triage",
  "max_generated_tasks": 1
}
```

### Parameter Reference

| Parameter           | Value          | How it is consumed by the plugin                            |
|---------------------|----------------|-------------------------------------------------------------|
| `path`              | `docs/roadmap.md` | Relative to the project's `primary_path`. File is read, parsed for unchecked TODO items. |
| `format`            | `markdown`      | Parser used: markdown handler scans for `- [ ]` lines.     |
| `profiles`          | `["implementer"]` | Assignee set on generated tasks.                          |
| `task_title_prefix` | `[plan]`        | Prefix prepended to generated task titles. Tasks carrying this prefix are replenish-eligible on completion. |
| `target_column`     | `triage`        | When set to `"triage"`, `create_task(triage=True)` forces the generated task's initial status to `triage` (a specifier is expected to promote it to `todo`). |
|| `max_generated_tasks` | `1`           | Caps the number of items pulled per replenishment cycle across ALL sources. The markdown handler respects this cap (returning 0 if the budget is exhausted); the JSON handler breaks its item loop when the count is reached. |

## Source Files

- **Source files**: `docs/roadmap.md`, `docs/product_backlog.md`, `docs/vision.md` — the JANUS planning documents in markdown format. The plugin parses unchecked TODO items (`- [ ] ...`) from each file and pulls the first one as a new task, checking it off in the file as it goes (cursor advancement).
- **Plugin implementation**: `~/.hermes/hermes-agent/plugins/replenishment/__init__.py`
- **Projects DB schema**: `~/.hermes/hermes-agent/hermes_cli/projects_db.py` (schema and `planning_sources` table)
- **Kanban task creation**: `hermes_cli/kanban_db.py` (`create_task` with `triage=True`)
- **Tests**: `tests/plugins/test_replenishment_plugin.py`

## Verification

The configuration is loaded and applied as follows (verified via E2E run on the
live Janus board — see `docs/research/e2e_replenishment_verification_janus.md`):

1. **Config load**: `projects_db.list_planning_sources(conn, "p_d550e150")`
   returns three `file` sources (`roadmap`, `product_backlog`, `vision`), each
   with `config_dict` containing `target_column: "triage"` and
   `max_generated_tasks: 1`.

2. **target_column applied**: The plugin's `_pull_from_markdown_roadmap`
   passes `triage=cfg.get("target_column") == "triage"` to `kb.create_task`,
   which forces the generated task's status to `triage` (see test
   `test_target_column_triage_marks_new_task_as_triage`).

3. **max_generated_tasks applied**: The markdown handler reads
   `cfg.get("max_generated_tasks", 1)` and returns 0 if the budget is
   exhausted (e.g. by a prior source in the same cycle or a re-fired hook
   that bypassed the seed-level guard). The JSON source handler reads
   `cfg.get("max_generated_tasks", cfg.get("batch_size", 1))` and breaks the
   item loop when the count is reached. Both handlers contribute to a global
   counter in `_replenish` that enforces the cap across all sources in a
   single cycle (see tests
   `test_markdown_respects_max_generated_tasks` and
   `test_max_generated_tasks_1_limits_json_pull_to_one`).

4. **E2E validation (live board)**: A `[plan]`-prefixed seed task was created
   and completed on the Janus board. Upon completion:
   - Exactly 1 new task was generated (from `docs/roadmap.md`, the only source
     with an unchecked `- [ ]` item at the time).
   - The generated task landed in `triage` status with `assignee=implementer`.
   - The item was checked off in `docs/roadmap.md` (cursor advancement).
   - An audit comment `[replenish] pulled 1 task(s) from 3 source(s) [file:product_backlog, file:roadmap, file:vision] after <seed_id> completed`
     was written on the seed task.
   - Re-firing the `kanban_task_completed` hook produced 0 new tasks and an
     audit comment `[replenish] pulled 0 task(s)` — confirming 3-layer
     idempotency (DB key dedup + cursor advancement + re-entrancy guard).
