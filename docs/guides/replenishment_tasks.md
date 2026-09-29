# Replenishment Task Construction and Roadmap Guide

This guide covers how the Hermes replenishment plugin constructs tasks and how to add new tasks to the roadmap. It is the operational companion to the configuration guide [`replenishment_sources.md`](replenishment_sources.md).

---

## 1. How Tasks Are Constructed

### The `[plan]` Prefix — Eligibility Gate

The replenishment plugin uses a **marker-prefix gate** to decide whether a completed task should trigger replenishment. Only tasks whose title starts with `[plan]` (configurable via `task_title_prefix`) are eligible.

When the plugin creates a new task, it **always prepends the prefix** to the title. This means:

- Tasks created by replenishment are themselves replenish-eligible.
- Completing a replenished task triggers another replenishment cycle.
- The chain continues until no unchecked items remain in any source.

**Example chain:**

```
[plan] Implement feature X        ← seed task (manually created or from roadmap)
  └─ [plan] Write tests for X    ← auto-created on completion
       └─ [plan] Review tests    ← auto-created on completion
            └─ ...               ← continues until sources are exhausted
```

### Task Fields Set by the Plugin

When the plugin pulls an item from a source, it constructs the new task with these fields:

| Field | Value | Notes |
|-------|-------|-------|
| `title` | `[plan] <item text>` | The prefix makes the task replenish-eligible. |
| `body` | Item text + metadata | Includes `#replenish source=...` and `#replenish parent=...` lines. |
| `assignee` | From source config (`profiles[0]`) | Defaults to the completed task's assignee if no profiles configured. |
| `parents` | `[completed_task.id]` | The new task is parented on the task that triggered replenishment. |
| `status` | `triage` (when `target_column == "triage"`) | Forces the task into triage for specifier review. |
| `idempotency_key` | `{project_id}:{source_id}:{item_id}` | Prevents duplicate tasks if the hook fires multiple times. |
| `project_id` | From the completed task | Inherited from the triggering task. |
| `integration_required` | `False` | Generated tasks are not integration tasks. |

### Body Metadata Format

The task body contains structured metadata for tracing:

```
<original item text>

#replenish source=roadmap
#replenish parent=t_abc123
```

These lines are machine-readable and used for audit trails. Do not remove them.

### Deferred Completion

Items are **not** marked `[x]` in the source file when they are pulled. Instead:

1. A `.complete` sidecar file (e.g., `docs/roadmap.md.complete`) tracks which items have been pulled.
2. Items are only marked `[x]` in the source file when the corresponding Kanban task is **actually completed**.
3. This prevents the same item from being pulled twice if the task is reopened or the hook re-fires.

### Idempotency — Three Layers

The plugin uses three independent mechanisms to prevent duplicate tasks:

1. **DB-level dedup** — `idempotency_key` on `create_task` prevents the same item from being created twice.
2. **Cursor advancement** — The `.complete` sidecar file tracks which items have been pulled, so the same item is never pulled again.
3. **Re-entrancy guard** — A thread-local set prevents nested replenishment cycles (e.g., when a swarm source auto-completes its root task).

### Per-Source Error Isolation

Each planning source is processed independently. If one source fails (e.g., a malformed roadmap file), the error is:

- Logged as a warning.
- Recorded as a structured comment on the completed task.
- **Does not prevent** other sources from running.
- **Does not prevent** the task completion from persisting.

---

## 2. How to Add New Tasks to the Roadmap

### Overview

The roadmap is a markdown file (`docs/roadmap.md`) with unchecked TODO items. The replenishment plugin parses these items and pulls them onto the board when a `[plan]`-prefixed task completes.

There is **no separate UI or API** for adding tasks. You edit the markdown file directly.

### Step-by-Step: Adding a Task to the Roadmap

**1. Open the roadmap file.**

```
docs/roadmap.md
```

**2. Add an unchecked TODO item** in the appropriate section:

```markdown
- [ ] Implement the new feature
```

The item must:
- Start with `- [ ]` (unchecked).
- Be on its own line.
- Have a clear, actionable description.

**3. Save the file.**

The plugin will automatically pick up the item on the next replenishment cycle.

**4. Trigger a replenishment cycle** by completing any `[plan]`-prefixed task on the board.

The plugin will:
- Find your new item (the first unchecked item in the file).
- Create a new task with the `[plan]` prefix.
- Parent it on the completed task.
- Place it in triage (if `target_column == "triage"`).

### Example: Adding a New Roadmap Item

Suppose you want to add a task for "Implement calendar integration":

**Before:**

```markdown
# Near-Term Implementation

- [x] Implement the execution planning extension
- [x] Implement the structured observability log schema
- [ ] Extend goal management with goal health
```

**After:**

```markdown
# Near-Term Implementation

- [x] Implement the execution planning extension
- [x] Implement the structured observability log schema
- [ ] Extend goal management with goal health
- [ ] Implement calendar integration
```

When the next `[plan]` task completes, the plugin will pull "Implement calendar integration" onto the board as `[plan] Implement calendar integration`.

### Adding Tasks to Other Sources

The same pattern applies to all configured planning sources:

| Source | File | Description |
|--------|------|-------------|
| Roadmap | `docs/roadmap.md` | Strategic direction and sequencing |
| Product Backlog | `docs/product_backlog.md` | Product capabilities and features |
| Vision | `docs/vision.md` | Long-term vision items |

Each source is processed independently. You can add items to any or all of them.

### JSON Source Format

If a source is configured with `format: "json"`, the file should contain either a list of items or a dict with an `items` list:

```json
[
  {"id": "item-1", "title": "Implement feature X", "body": "Detailed description"},
  {"id": "item-2", "title": "Write tests for X", "body": "Test coverage requirements"}
]
```

Or:

```json
{
  "items": [
    {"id": "item-1", "title": "Implement feature X", "body": "Detailed description"}
  ]
}
```

Each item must have `id`, `title`, and `body` fields.

### The `.complete` Sidecar File

When the plugin pulls an item, it records the item's ID in a `.complete` sidecar file:

```
docs/roadmap.md.complete
```

This file is **managed by the plugin**. Do not edit it manually. It tracks which items have been pulled to prevent duplicates.

If you need to reset the cursor (e.g., to re-pull all items), delete the `.complete` file:

```bash
rm docs/roadmap.md.complete
```

The next replenishment cycle will start from the beginning of the file.

---

## 3. Complete Workflow Example

Here is the end-to-end workflow for a typical replenishment cycle:

```
1. You add an item to docs/roadmap.md:
   - [ ] Implement calendar integration

2. You complete a [plan] task on the board:
   [plan] Extend goal management with goal health → marked done

3. The replenishment plugin fires:
   - Detects the [plan] prefix on the completed task.
   - Loads planning sources from projects.db.
   - Finds "Implement calendar integration" as the next unchecked item.
   - Creates a new task:
     Title: [plan] Implement calendar integration
     Status: triage
     Parent: t_abc123 (the completed task)
     Body: "Implement calendar integration\n\n#replenish source=roadmap\n#replenish parent=t_abc123"

4. The new task appears in triage on the board.

5. A specifier reviews the task and promotes it to todo.

6. An implementer works on the task and completes it.

7. The plugin fires again (because the task has [plan] prefix):
   - Finds the next unchecked item in the roadmap.
   - Creates another new task.
   - The cycle continues.
```

---

## 4. Troubleshooting

### Replenishment does not fire

- **Check the prefix**: The completed task's title must start with `[plan]` (or the configured `task_title_prefix`).
- **Check the plugin is enabled**: Run `hermes plugins list` and verify `replenishment` is enabled.
- **Check sources are configured**: Verify `projects.db` has planning sources for the project.
- **Check the roadmap file exists**: The `path` in the source config must point to a valid file.

### The same item is pulled multiple times

- **Check the `.complete` file**: Delete it to reset the cursor.
- **Check for duplicate items**: The same item text on multiple lines will be treated as separate items.

### Tasks are created in the wrong status

- **Check `target_column`**: If set to `"triage"`, tasks are created in triage. If unset, they default to `todo`.

### The plugin creates too many tasks

- **Check `max_generated_tasks`**: This caps the number of tasks created per cycle across all sources. Default is `1`.

---

## 5. Related Documentation

- [`replenishment_sources.md`](replenishment_sources.md) — Configuration guide for planning sources
- [`docs/roadmap.md`](../roadmap.md) — The Janus roadmap (primary planning source)
- [`docs/product_backlog.md`](../product_backlog.md) — Product backlog (secondary source)
- [`docs/vision.md`](../vision.md) — Vision document (tertiary source)
