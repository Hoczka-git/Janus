# Decomposition Plan — t_c04a3f46

**Date:** 2026-09-06
**Researcher:** researcher
**Source:** Janus repository @ `/home/dan11hermes/workspaces/janus`

---

## 1. Current State (Evidence)

### 1.1 Done — Goal Execution Planning

All artifacts from `DESIGN_EXECUTION_PLANNING.md` exist in `src/janus/`:

| Artifact | File | Lines |
|----------|------|-------|
| Milestone dataclass | `models/milestone.py` | 31 |
| Goal.milestones field | `models/goal.py:28` | — |
| Milestone CRUD | `services/milestones.py` | 158 |
| Next-action derivation | `services/next_action.py` | 248 |
| Extended stall signals | `services/attention.py:61-119` | — |
| Weekly review integration | `services/weekly_review.py:15,86-91` | — |
| Milestone CLI | `goals_cli.py:512-760` | — |
| Goal next CLI | `goals_cli.py:751` | — |
| Milestone persistence | `integrations/markdown_goals.py:33-93,257-259` | — |

Tests: `test_milestone_model`, `test_milestone_persistence`, `test_milestones_service`, `test_next_action`, `test_attention_extended`, `test_goal_next`, `test_goals_cli_milestones`, `test_derive_milestone_tasks` — all pass (884 total).

### 1.2 Done — Integration Contract (Hermes core)

`hermes_cli/kanban_db.py:3515-3520` — `_resolve_integration_required()`, `_ensure_integration_required_frontmatter()`, body injection, `created` event payload. Design matches `integration_contract_final_design.md` §2.1.

Note: Hermes CLI currently has an IndentationError at `kanban_db.py:3522` (separate issue, not in scope).

### 1.3 NOT Done — Observability

- `src/janus/logging_config.py` — does NOT exist
- Zero `logging` imports in any module
- Zero structured events (`janus.command.started`, etc.)
- `OBSERVABILITY_PLAN.md` status: "Plan only — do not implement" (dated 2026-09-01)

### 1.4 NOT Done — Roadmap-Driven Replenishment

- Product backlog: `[ready] Configure roadmap-driven replenishment for Janus`
- No replenishment configuration exists in the repo

### 1.5 Stale — Roadmap

`docs/roadmap.md` line 94: `[ ] Implement the execution planning extension` — unchecked despite full implementation.

---

## 2. Assumptions & Constraints

- Profiles available: researcher, implementer, integrator, reviewer (per task spec)
- Hermes CLI is currently broken (IndentationError in `kanban_db.py:3522`) — may affect reviewer tasks that run `hermes` commands
- Observability plan is dated 2026-09-01; validate before implementing
- No new runtime dependencies (per observability plan §6)
- Python 3.11+, stdlib only
- 884 existing tests must continue to pass

---

## 3. Task Graph (Decomposition)

### Child tasks (all parent: t_c04a3f46)

| # | ID | Title | Profile | integration_required | Notes |
|---|----|-------|---------|---------------------|-------|
| 1 | t_c04a3f46_r1 | Research: Verify execution planning acceptance criteria | researcher | false | Verify DESIGN_EXECUTION_PLANNING.md §9 checklist against current code |
| 2 | t_c04a3f46_r2 | Research: Validate observability plan readiness | researcher | false | Confirm OBSERVABILITY_PLAN.md is current, stdlib appropriate, no blockers |
| 3 | t_c04a3f46_i1 | Implement: Observability instrumentation | implementor | true | Create logging_config.py + instrument all modules per §5 |
| 4 | t_c04a3f46_rv1 | Review: Observability output verification | reviewer | true | Validate log format, event catalog, no secret leakage |
| 5 | t_c04a3f46_r3 | Research: Hermes replenishment plugin API | researcher | false | Investigate Hermes replenishment plugin capabilities & config for Janus |
| 6 | t_c04a3f46_i2 | Implement: Roadmap-driven replenishment | implementor | true | Configure replenishment per backlog, max_generated_tasks=1, target TRIAGE |
| 7 | t_c04a3f46_rv2 | Review: Replenishment end-to-end validation | reviewer | true | Verify idempotency, audit trail, generated task quality |
| 8 | t_c04a3f46_i3 | Implement: Roadmap accuracy update | implementor | true | Mark execution planning done in roadmap.md |

### Dependency graph

```
t_c04a3f46 (this task — decompose plan)
├── t_c04a3f46_r1 (verify execution planning) ─→ t_c04a3f46_i3 (update roadmap)
├── t_c04a3f46_r2 (validate observability) ─→ t_c04a3f46_i1 (implement observability) ─→ t_c04a3f46_rv1 (verify)
├── t_c04a3f46_r3 (research replenishment) ─→ t_c04a3f46_i2 (configure replenishment) ─→ t_c04a3f46_rv2 (validate)
```

All children have `parents=[t_c04a3f46]`. Sequencing within each chain:
- i1 depends on r2 (research validates before implementation)
- i3 depends on r1 (verification before roadmap update)
- i2 depends on r3 (research API before configuration)
- rv1 depends on i1 (review after implementation)
- rv2 depends on i2

---

## 4. Task Specifications

### 4.1 t_c04a3f46_r1 — Verify Execution Planning Acceptance Criteria

**Goal:** Walk the DESIGN_EXECUTION_PLANNING.md §9 checklist and verify each criterion passes against the current codebase.

**Method:**
- For each checkbox in §9.1–§9.7, find the corresponding code and verify behavior
- Run `python -m pytest tests/test_milestone_model.py tests/test_milestone_persistence.py tests/test_milestones_service.py tests/test_next_action.py tests/test_attention_extended.py tests/test_goal_next.py tests/test_goals_cli_milestones.py tests/test_derive_milestone_tasks.py tests/test_markdown_goals.py tests/test_weekly_review.py tests/test_attention.py -q` and confirm pass
- Output: pass/fail per criterion with file:line evidence

**Acceptance:** Every §9 criterion is verified as passing or flagged with specific gap evidence.

---

### 4.2 t_c04a3f46_r2 — Validate Observability Plan Readiness

**Goal:** Confirm OBSERVABILITY_PLAN.md assumptions hold before implementation.

**Method:**
- Check Python version compatibility (3.11+)
- Verify no conflicting logging config already exists in Janus
- Confirm `janus` logger namespace is free (no third-party library uses it)
- Verify pyproject.toml dependency constraints (no new runtime deps)
- Check that all target files/modules listed in §5 exist at the specified paths
- Verify Telegram `chat_id` logging is acceptable per user profile (Polish/English, privacy-conscious)

**Acceptance:** Go/no-go recommendation for implementing OBSERVABILITY_PLAN.md as-is, or specific updates needed.

---

### 4.3 t_c04a3f46_i1 — Implement Observability Instrumentation

**Goal:** Add structured logging per OBSERVABILITY_PLAN.md.

**New file:**
- `src/janus/logging_config.py` — `setup_logging(verbose: bool)` per §1.2

**Modified files (per §5):**

| File | Change |
|------|--------|
| `__init__.py` | Import logging_config, call setup_logging, add `--verbose` flag, instrument main() with started/finished |
| `today.py` | Instrument `_build_today_briefing()` with generation_started/finished |
| `weekly_review.py` | Instrument `create_weekly_review()` with generation_started/finished |
| `google_calendar.py` | Instrument `list_upcoming_events()` loop with source.calendar_fetched |
| `markdown_tasks.py` | Instrument `load_tasks()` with source.tasks_loaded |
| `markdown_goals.py` | Instrument `load_goals()` with source.goals_loaded |
| `workout_md.py` | Instrument `load_workouts()` with source.workouts_loaded (contingent) |
| `attention.py` | Instrument `get_attention_items()` with engine.attention_computed |
| `telegram.py` | Instrument `send_briefing()` with delivery.telegram_sent |
| `telegram_weekly.py` | Instrument `send_weekly()` with delivery.telegram_sent |
| `tasks.py` | Instrument add/complete/set_state/set_progress with service.task_write |
| `goals.py` | Instrument add/update_fields/complete with service.goal_write |

**Implementation rules:**
- Use inline JSON message format (§4.1): `logger.info(json.dumps({...}))`
- Pass `briefing_id` explicitly as optional kwarg (default None) through the call chain (§3.1)
- Use `time.monotonic()` for durations (§3.2)
- Never log `bot_token` or full exception tracebacks (§4.3)

**Acceptance:** All 12 event types from §2 fire correctly; existing 884 tests pass; stderr output matches format in §4.1.

---

### 4.4 t_c04a3f46_rv1 — Review: Observability Output Verification

**Goal:** Verify observability implementation produces correct, safe, parseable output.

**Method:**
- Run `janus today --verbose` and `janus weekly --verbose` — confirm started/finished events fire with correct fields
- Verify JSON parseability of every log line on stderr
- Confirm NO `bot_token`, `chat_id` (per privacy), or exception tracebacks in structured output
- Verify `briefing_id` correlates all events within a single run
- Check all 12 event types from §2 are reachable
- Run full test suite — 884+ tests pass

**Acceptance:** All 12 events documented, format parseable, no secrets, no regressions.

---

### 4.5 t_c04a3f46_r3 — Research Hermes Replenishment Plugin API

**Goal:** Investigate Hermes replenishment plugin capabilities to configure it for Janus.

**Method:**
- Search Hermes docs/skills for replenishment plugin configuration
- Identify: supported planning source formats, `max_generated_tasks` behavior, TRIAGE targeting mechanism, idempotency guarantees, audit trail output
- Determine: does Janus need a `roadmap.md` / `product_backlog.md` parser, or does Hermes handle this natively?
- Check: how does replenishment handle stale items (e.g., execution planning already done)?

**Acceptance:** Clear configuration spec: what sources to register, what params to set, what validation to perform.

---

### 4.6 t_c04a3f46_i2 — Implement Roadmap-Driven Replenishment

**Goal:** Configure Hermes replenishment for Janus per product backlog.

**Requirements (from backlog):**
- Enable replenishment
- Register planning sources: `docs/roadmap.md`, `docs/product_backlog.md`, `docs/vision.md`
- `max_generated_tasks = 1`
- Target generated tasks to TRIAGE
- Idempotency and audit trail validation

**Acceptance:** Replenishment generates tasks from planning sources, respects max_generated_tasks, targets TRIAGE.

---

### 4.7 t_c04a3f46_rv2 — Review: Replenishment End-to-End Validation

**Goal:** Validate replenishment works correctly in production.

**Method:**
- Trigger replenishment manually
- Verify generated task lands in TRIAGE with correct source attribution
- Trigger again — verify idempotency (no duplicates)
- Verify audit trail captures generation event

**Acceptance:** Idempotent, audited, correctly targeted task generation confirmed.

---

### 4.8 t_c04a3f46_i3 — Update Roadmap Accuracy

**Goal:** Mark execution planning as done in `docs/roadmap.md`.

**Change:**
```markdown
- [x] Implement the execution planning extension described in
  [`DESIGN_EXECUTION_PLANNING.md`](../DESIGN_EXECUTION_PLANNING.md)
```

**Acceptance:** Roadmap reflects actual implementation status.

---

## 5. Risks & Open Questions

| Risk | Impact | Mitigation |
|------|--------|------------|
| OBSERVABILITY_PLAN.md stale since 2026-09-01 | Implementation may not match current best practices | r2 validates before i1 implements |
| Hermes CLI broken (IndentationError) | Reviewer can't run `hermes` commands to validate | Fix CLI first, or reviewer uses direct Python invocation |
| `chat_id` logging may conflict with user privacy preference | Privacy concern | r2 must confirm; if rejected, redact chat_id in telegram events |
| Replenishment plugin API not well-documented | Configuration may fail | r3 researches before i2 implements |

---

## 6. Recommended Sequencing

1. **Phase 1 (parallel):** r1, r2, r3 — all research, no dependencies
2. **Phase 2 (after r2):** i1 — observability implementation
3. **Phase 3 (after r1):** i3 — roadmap update (quick win)
4. **Phase 4 (after r3):** i2 — replenishment configuration
5. **Phase 5 (after i1, i2):** rv1, rv2 — independent reviews

---

*integration_required: false (decomposition/research task — no PR needed)*
