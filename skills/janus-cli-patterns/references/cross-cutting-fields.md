# Cross-cutting field propagation

When a new field is added to a Janus domain model, it must flow through every layer that
touches the model. This reference records the worked example from the `Task.state` /
`Task.progress` implementation so a future session can reproduce or audit the chain.

## Layers

| # | Layer | File | Responsibility |
|---|-------|------|----------------|
| 1 | Domain model | `src/janus/models/task.py` | Dataclass field + `__post_init__` validation. Export constants like `ALLOWED_STATES`. |
| 2 | Persistence parse | `src/janus/integrations/markdown_tasks.py` | Extract new field from markdown metadata in `_parse_task_line`. Preserve unknown fields via `_extract_unknown_metadata`. |
| 3 | Persistence format | `src/janus/integrations/markdown_tasks.py` | Write new field in `_format_task_line`. Known fields normalized; unknown fields appended. |
| 4 | Service | `src/janus/services/tasks.py` | Read file, find matching open task, mutate field, rewrite. Preserve all other metadata. |
| 5 | CLI handler | `src/janus/tasks_cli.py` | Parse CLI args, validate against model constants, call service, print confirmation. |
| 6 | Dispatcher | `src/janus/__init__.py` | Wire handler into `main()` dispatch tree under the right command/subcommand. |
| 7 | Attention scoring | `src/janus/services/attention.py` | If the field affects prioritization, update `get_attention_items` and add scoring tests. |

## Worked example: `state` and `progress`

### What was added

- `Task.state: str | None` — one of `todo`, `in_progress`, `blocked`
- `Task.progress: int | None` — integer 0–100
- `ALLOWED_STATES = frozenset({"todo", "in_progress", "blocked"})`

### Propagation evidence (verified from real files)

1. **Model** — `src/janus/models/task.py` has both fields with `__post_init__` validation.
2. **Parse** — `markdown_tasks.py` has `_parse_state`, `_parse_progress`, `_extract_unknown_metadata`.
3. **Format** — `markdown_tasks.py` `_format_task_line` writes `state:` and `progress:` and appends `extra_metadata`.
4. **Service** — `services/tasks.py` has `set_task_state` and `set_task_progress`, each reading the file, matching the open task, mutating, and rewriting.
5. **CLI** — `tasks_cli.py` has `handle_task_state` (`--state`) and `handle_task_progress` (`--pct`).
6. **Dispatcher** — `__init__.py` imports both handlers and dispatches on `state`/`progress` subcommands.
7. **Attention** — `attention.py` already scored `state == "blocked"` (+30) and `state == "in_progress"` (+30) before tests existed.

### Why layer 7 matters

The attention engine referenced `task.state` before any dedicated tests existed. Without
tests, a future refactor could silently remove the scoring. Always add at least one
attention-scoring test per new field that affects prioritization.

## Test gaps and how to fill them

The existing test suite (as of this writing) did NOT have tests for:
- `handle_task_state` CLI output
- `handle_task_progress` CLI output
- `set_task_state` service behavior
- `set_task_progress` service behavior
- attention scoring with `state`/`progress` fields
- persistence parse/format round-trip for `state`/`progress`

A complete implementation should add tests at each layer that carries the field, not just
the CLI layer. At minimum:
- CLI handler tests (capsys + mocked service, matching the `test_tasks_cli.py` style)
- Service tests (isolated tmp_path, real file read/write)
- Attention tests (task with `state="blocked"` produces +30; task with `state="in_progress"` produces +30)
- Persistence round-trip tests (write a task with state/progress, read it back, assert fields)

## When to use this checklist

- Any new field on a Janus domain model.
- Auditing whether a partially-implemented feature has gaps.
- Reviewing a PR that adds a field — verify every layer in the table above is touched.
