# Unified Inbox and Follow-Up Model — Implementation Plan

> **Status:** Implemented. All phases complete. 1237 baseline tests passing.
> **Source:** `docs/unified_inbox_followup_design.md` (643 lines, design complete)
> **Primary implementation contract:** This document.
> **Repo baseline:** `data/tasks.md` is gitignored; all persistence code resolves `data/*.md` paths via `PROJECT_ROOT = Path(__file__).resolve().parents[3]`. Existing test baseline: 1237 passed.

---

## 1. EXECUTIVE SUMMARY

This plan converts the design spec (`docs/unified_inbox_followup_design.md`) into a concrete, phased implementation contract. It adds two new dataclasses (`InboxItem`, `FollowUp`), two new markdown persistence modules, two new services, and one CLI module — all following the exact patterns already established by `Task`/`Goal`/`Milestone`.

The single integration point with existing code is the **attention engine** (`src/janus/services/attention.py`), where FollowUps are added as a new scoring category. The daily briefing picks them up automatically because it consumes attention items (no briefing logic change needed).

No existing models, services, data files, or CLI surfaces are modified in their behavior — only additive changes.

---

## 2. ARCHITECTURE DECISIONS (carried from the design spec)

|| # | Decision | Rationale |
||---|----------|-----------|
|| 1 | Separate `InboxItem` and `FollowUp` dataclasses (not one model) | Capture and tracking are different concerns |
|| 2 | Separate `data/inbox.md` and `data/followups.md` files (not added to `tasks.md`) | Different entities with different fields/states |
|| 3 | Pipe-delimited metadata, same as `tasks.md` | Uniform parsing across all three domain stores |
|| 4 | FollowUp.id carries InboxItem.id on triage-originated conversion | Clean traceability chain |
|| 5 | No auto-triage in MVP | Reduces misclassification risk |
|| 6 | `scheduled_for` separate from `due_date` | Intended work date ≠ deadline |
|| 7 | FollowUp completes (not re-opened) at Task conversion | Prevents double-counting in attention + briefing |

---

## 3. PHASE A — DOMAIN MODEL (IMPLEMENTED)

### 3.1 File: `src/janus/models/inbox.py` (CREATE — done)

`InboxItem` dataclass with fields: id, captured_text, source, captured_at, context, triage_state, triage_note, triage_at, linked_goal_title, linked_research_title.

**Line format for `data/inbox.md`:**
```
ix-<id> | <captured_text> | source: <source> | captured_at: <iso> | context: <context> | state: <triage_state> | triage_note: <note> | triage_at: <iso> | goal: <title> | research: <title>
```

### 3.2 File: `src/janus/models/follow_up.py` (CREATE — done)

`FollowUp` dataclass with fields: id, title, originating_inbox_id, state, priority, due_date, scheduled_for, assigned_to, created_at, completed_at, created_by, note, linked_goal_title, linked_task_title, converted_to_task_title.

**Line format for `data/followups.md`:**
```
fu-<id> | <title> | state: <state> | priority: <n> | due: <iso> | scheduled: <iso> | assigned_to: <who> | created_at: <iso> | completed_at: <iso> | created_by: <source> | note: <note> | goal: <title> | linked_task: <title> | converted_to_task: <title>
```

### 3.3 File: `src/janus/models/__init__.py` (MODIFY — done)

Added imports for `InboxItem`, `FollowUp` and corresponding `__all__` entries.

---

## 4. PHASE B — PERSISTENCE (IMPLEMENTED)

### 4.1 File: `src/janus/integrations/markdown_inbox.py` (CREATE — done)

Pattern: mirror of `markdown_tasks.py`. Functions: `load_inbox_items`, `_parse_inbox_line`, `_format_inbox_line`, `save_inbox_item`, `update_inbox_item`.

- Returns `[]` when file missing (goals pattern, not tasks pattern).
- Rewrite strategy for `update_inbox_item`: read all lines, find matching id, replace, write all back.

### 4.2 File: `src/janus/integrations/markdown_followups.py` (CREATE — done)

Same pattern for `FollowUp`. Functions: `load_followups`, `_parse_followup_line`, `_format_followup_line`, `save_followup`, `update_followup`.

### 4.3 Test fixtures

`data/` is gitignored. Tests use `tmp_path` + `monkeypatch` to swap path constants.

---

## 5. PHASE C — SERVICES (IMPLEMENTED)

### 5.1 File: `src/janus/services/inbox.py` (CREATE — done)

CRUD + triage service. Functions: `add_inbox_item`, `triage_item`, `list_inbox_items`, `get_inbox_item`.

- ID generation: `ix-` + `uuid.uuid4().hex[:8]`
- Triage invariant: once triaged (discarded/converted/follow_up), further triage raises ValueError.

### 5.2 File: `src/janus/services/followup.py` (CREATE — done)

CRUD + lifecycle service. Functions: `add_followup`, `get_followup`, `list_followups`, `set_followup_state`, `schedule_followup`, `complete_followup`, `convert_followup_to_task`.

- State transitions: validates target state is in FOLLOWUP_STATES but does NOT enforce transition matrix (design §7.2).
- `convert_followup_to_task`: marks follow-up completed + records `converted_to_task_title`. CLI creates the actual Task via `services.tasks.add_task`.

---

## 6. PHASE D — ATTENTION ENGINE INTEGRATION (IMPLEMENTED)

### 6.1 File: `src/janus/services/attention.py` (MODIFY — done)

Added `followups` parameter (optional, defaults to None for backward compatibility). FollowUp scoring block with 7 conditions:

|| Condition | Score | Category |
||-----------|-------|----------|
|| `due_date` past, not completed | 100 | `follow_up_overdue` |
|| `due_date` today | 80 | `follow_up_due_today` |
|| `scheduled_for` today, state scheduled/pending | 60 | `follow_up_scheduled_today` |
|| `scheduled_for` within 3 days, state scheduled | 40 | `follow_up_scheduled_soon` |
|| state == blocked | 50 | `follow_up_blocked` |
|| state == in_progress | 30 | `follow_up_in_progress` |
|| pending, no schedule, older than 7 days | 20 | `follow_up_stale` |

Priority boost: priority 4-5 adds +30, priority 3 adds +20 (when score > 0).

### 6.2 File: `src/janus/services/daily_briefing.py` (MODIFY — done)

Added `followups` param, forwarded to `get_attention_items`.

### 6.3 File: `src/janus/today.py` (MODIFY — done)

Loads follow-ups via `load_followups()` and passes them to `create_daily_briefing`.

---

## 7. PHASE E — CLI (IMPLEMENTED)

### 7.1 File: `src/janus/inbox_cli.py` (CREATE — done)

Handlers: `handle_inbox_list`, `handle_inbox_triage`, `handle_inbox_pending`, `print_inbox_help`.

- `handle_inbox_triage --followup`: creates FollowUp from InboxItem, carries id
- `handle_inbox_triage --discard`: sets state to discarded
- `handle_inbox_triage --convert-to-task`: creates Task via `add_task()`, sets triage_state to converted

### 7.2 File: `src/janus/followup_cli.py` (CREATE — done)

Handlers: `handle_followup_list`, `handle_followup_add`, `handle_followup_show`, `handle_followup_update`, `handle_followup_complete`, `handle_followup_convert`, `print_followup_help`.

### 7.3 File: `src/janus/__init__.py` (MODIFY — done)

Added imports and dispatch branches for `inbox` and `followup` commands.

---

## 8. FILE MANIFEST

### Files created (8):

- `src/janus/models/inbox.py`
- `src/janus/models/follow_up.py`
- `src/janus/integrations/markdown_inbox.py`
- `src/janus/integrations/markdown_followups.py`
- `src/janus/services/inbox.py`
- `src/janus/services/followup.py`
- `src/janus/inbox_cli.py`
- `src/janus/followup_cli.py`

### Files modified (5):

- `src/janus/models/__init__.py`
- `src/janus/services/attention.py`
- `src/janus/services/daily_briefing.py`
- `src/janus/today.py`
- `src/janus/__init__.py`

### Files NOT modified (by design):

- `src/janus/models/task.py`
- `src/janus/services/tasks.py`
- `src/janus/integrations/markdown_tasks.py`
- `data/tasks.md`

---

## 9. TEST RESULTS

Baseline: **1237 passed, 0 failed**. No regressions.

---

## 10. VERIFICATION

Run: `uv run pytest tests/ -q` — all 1237 existing tests pass.
CLI smoke test:
```
uv run python3 -m janus inbox --help
uv run python3 -m janus followup --help
```
