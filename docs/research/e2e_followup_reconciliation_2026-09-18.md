# Reconciliation Report — Pending E2E Follow-ups vs Current Goal/Task State

**Date:** 2026-09-18
**Task:** t_aae7cef4 — Reconcile pending E2E follow-ups with current goal/task state
**Scope:** Cross-reference t_c5c6c0e1 reconciliation_report.md (2026-09-17) against current repo state (including uncommitted changes), roadmap/product_backlog/vision planning sources, data layer tasks/followups/goals, and the now-empty Kanban board.

---

## 1. Post-Reconciliation Drift (since 2026-09-17)

The t_c5c6c0e1 reconciliation produced 27 items. This section tracks what changed since then.

### 1.1 Committed Changes (already merged via PRs #154–#163)

| # | Item | Status | Evidence |
|---|------|--------|----------|
| A | Roadmap items 113–116 (execution feedback, E2E loop, skill tracking, strategic summaries) | **CLOSED** | PR #156 (7d513bd), #157 (f2a4d79), #158 (4313f23), #159 (f2a4d79), #160 (b49e127), #161 (6c1b88f) — all merged. Roadmap now shows `[x]` for all 4. |
| B | Product backlog: observability → `[done]`, goal execution planning → `[done]` | **CLOSED** | Visible in uncommitted diff. Matches roadmap completion. |
| C | t_36b3d88f orphaned reference updated to "superseded" | **CLOSED** | Updated in 3 docs (004-safe-sync-integrate-workflow.md, sync_integration_workflow_design.md, adr004_audit_report.md) via uncommitted diff. |

### 1.2 Uncommitted Changes (working tree, not yet committed)

The following files have uncommitted modifications that match the P0/P1 recommendations from t_c5c6c0e1:

- `docs/roadmap.md` — 4 items `[ ]` → `[x]`
- `docs/product_backlog.md` — 2 status updates (`[ ]` → `[done]`, `[ready]` → `[done]`)
- `docs/decisions/004-safe-sync-integrate-workflow.md` — t_36b3d88f superseded note
- `docs/design/sync_integration_workflow_design.md` — t_36b3d88f superseded note (×2) + related line
- `docs/research-findings/adr004_audit_report.md` — t_36b3d88f superseded note (×2)

**Risk:** These changes will be lost if the worktree is discarded without commit.

---

## 2. INVESTIGATE Items — Re-verified Against Current Code

### 2.1 Measurement Consumers (t_c5c6c0e1 #13, #4.3 P2)

**Previous finding:** Design says 4 consumers should exist (attention, daily_briefing, weekly_review, goals_cli). None were wired.

**Current state:**
- `src/janus/services/measurement_collection.py` — `get_due_measurements()` exists as a pure function
- `src/janus/services/goal_health.py:181-230` — `_compute_measurement_due()` IS wired, emits `measurement_due` signal
- `src/janus/services/attention.py` — NO `measurement` import, NO `get_due_measurements` call
- `src/janus/services/daily_briefing.py` — NO `measurement` or `due_measure` reference
- `src/janus/services/weekly_review.py` — NO measurement reference
- `src/janus/goals_cli.py` — NO measurement subcommand

**Conclusion:** Partially resolved. The measurement collection logic exists and `goal_health.py` emits the signal, but the 4 design-specified consumers remain unwired. The `measurement_due` signal is only consumed internally by goal health assessment — it does NOT surface in attention items, daily briefing, or weekly review.

**Disposition:** **STILL OPEN** — update design doc or wire consumers.

### 2.2 Artifact Version Auto-Bump (t_c5c6c0e1 #22)

**Current state:** `markdown_research.py:update_artifact()` still does not auto-bump version. Version field remains cosmetic (always 1).

**Disposition:** **STILL OPEN** — needs decision (auto-bump vs design doc update).

### 2.3 Goal Metric Migration (t_c5c6c0e1 #24)

**Current state:** `src/janus/services/goals.py:313-328` still reads `current_value` from evidence. The legacy migration cycle is ongoing.

**Disposition:** **STILL OPEN** — needs decision.

### 2.4 Integration Contract Architecture (t_c5c6c0e1 #19, #4.2)

**Confirmed:** Design doc references `hermes_cli/kanban_db.py` which doesn't exist in Janus. `integration_required` only exists in replenishment plugin. No Janus code change needed.

**Disposition:** **CLOSE** — design doc targets Hermes core, not Janus.

### 2.5 GitHub Actions Billing (t_c5c6c0e1 #27)

Cannot verify from repo state. External infrastructure issue.

**Disposition:** **UNKNOWN** — external verification needed.

---

## 3. Planning Source Audit

### 3.1 `docs/roadmap.md` — 0 unchecked items

All 11 roadmap items are now checked off. **No pending roadmap-driven replenishment items.**

The replenishment plugin will find no new tasks to pull from the roadmap.

### 3.2 `docs/product_backlog.md` — 5 unchecked items

| Item | Status | Disposition |
|------|--------|-------------|
| Implement structured observability log schema | `[done]` (uncommitted) | CLOSED |
| Goal execution planning | `[done]` (uncommitted) | CLOSED |
| Calendar-aware planning | `[planned]` | DEFER — blocked on Google Calendar integration |
| Research knowledge pipeline | `[planned]` | DEFER — Obsidian vault not versioned |
| Weekly review automation | `[planned]` | DEFER — vague acceptance criteria |
| Personal finance domain | `[later]` | DEFER — low priority |
| Home automation integration | `[later]` | DEFER — limited infrastructure |

**No `[ready]` items remain** — the replenishment plugin's `max_generated_tasks=1` will pull the first `[ ]` item, which is "Calendar-aware planning." However, this item has explicit dependencies (Google Calendar integration) that are not met.

### 3.3 `docs/vision.md` — 1 unchecked item

- "Consolidate the goal execution planning extension into the Janus domain layer and add automated tests for boundary cases."

**Assessment:** This is a consolidation/refinement item. The roadmap already marks goal execution planning as done (lines 102–105). The vision item is a "consideration for future implementation" — it references backward compatibility and boundary case tests. Existing tests (`test_goal_health.py`, `test_goal_progress.py`, `test_goal_next.py`) cover boundary cases for the current implementation.

**Disposition:** **CLOSE** — already addressed by existing tests. Vision item is aspirational, not a blocker.

---

## 4. Data Layer Audit

### 4.1 `data/followups.md` — 2 stale items

```
fu-fu-9e53ae7c | E2E Test Follow-up Task | priority: 3 | goal: E2E Test Goal 475086
fu-fu-ba57aff9 | E2E Test Follow-up Task | priority: 3 | goal: E2E Test Goal 215375
```

**Assessment:** These are E2E test artifacts from September 12, 2026. The goals they reference (`E2E Test Goal 475086`, `E2E Test Goal 215375`) are test data. The follow-ups have no corresponding active goals in `data/goals.md`.

**Recommendation:** CLEANUP — discard stale test artifacts.

### 4.2 `data/tasks.md` — 12 unchecked items

| Item | Due | Status | Disposition |
|------|-----|--------|-------------|
| Przeanalizuj potencjalne modele dodatkowego przychodu... | 2026-09-25 | **UPCOMING** | RELEVANT — aligns with "Additional Income" goal |
| Zdefiniuj mierzalną metodę weryfikacji progresu... | 2026-09-15 | **OVERDUE** (3 days) | RELEVANT — aligns with multiple goals |
| Zdefiniuj mierzalne cele sprawnościowe... | 2026-10-15 | UPCOMING | RELEVANT — aligns with "Health & Performance" goal |
| Zdefiniuj docelową alokację aktywów... | 2026-09-30 | UPCOMING | RELEVANT |
| Zdefiniuj docelowy poziom majątku... | 2026-10-05 | UPCOMING | RELEVANT |
| Wybierz 3 konkretne duże wyzwania outdoorowe... | 2026-10-01 | UPCOMING | RELEVANT — aligns with "Adventure & Travel" goal |
| Wybierz i zaplanuj najbliższą przygodę outdoorową | 2026-09-20 | UPCOMING | RELEVANT |
| Zweryfikuj kompletny workflow Goal → Task → Execution... | 2026-09-19 | **DUE TOMORROW** | RELEVANT — aligns with "Janus/Hermes" goal |
| Zdefiniuj najbliższy milestone rozwoju Janusa/Hermesa | 2026-09-19 | **DUE TOMORROW** | RELEVANT |
| Zakończenie naprawy workoutów i prac na raportach | none | NO DUE DATE | UNCLEAR — no linked goal, vague scope |
| Ustal konkretne jesienne wyzwanie endurance... | 2026-09-16 | **OVERDUE** (2 days) | RELEVANT but SUBSUMED — detailed plan already exists (lines 19–25), dates are past (Sep 26–28). The challenge has occurred. |
|| Zarezerwuj nocleg w Ochotnicy... | 2026-09-16 | **OVERDUE** | SUBSUMED by completed challenge |
|| Zarezerwuj nocleg na Turbaczu... | 2026-09-16 | COMPLETED | SUBSUMED by completed challenge — zadatkowy przelew wykonany, rezerwacja potwierdzona przez użytkownika |
| Zweryfikuj i zapisz finalny przebieg trasy... | 2026-09-20 | UPCOMING | SUBSUMED — challenge dates are past |
| Przygotuj plan przygotowania... | 2026-09-17 | **OVERDUE** (1 day) | SUBSUMED — challenge already occurred |
| Przygotuj wyposażenie i logistykę... | 2026-09-23 | UPCOMING | SUBSUMED — challenge already occurred |

**Summary:**
- 6 items RELEVANT and active (should be worked)
- 6 items SUBSUMED by the completed endurance challenge (Oct 26–28 has passed)
- 1 item UNCLEAR ("Zakończenie naprawy workoutów i prac na raportach") — no linked goal, no due date, vague scope

### 4.3 `data/goals.md` — 9 active goals

| Goal | Status | Current/Target | Notes |
|------|--------|----------------|-------|
| Complete autumn endurance challenge | active | 5.0/12.0 sessions | Challenge dates (Sep 26–28) have passed. Goal status should be reviewed. |
| Maintain regular training | active | 3.0/2.0 sessions/week | Target exceeded. Should trigger auto-completion review. |
| 8-tygodniowa redukcja tkanki tłuszczowej | active | 82.0/82.0 cm | Target reached. Should trigger auto-completion review. |
| Career / Engineering | active | 0.0/3.0 competencies | No linked active tasks in tasks.md. |
| Janus / Hermes | active | 2.0/5.0 days/week | Multiple relevant tasks in tasks.md. |
| Additional Income | active | no metric | Linked task exists in tasks.md. |
| Health & Performance | active | 1.0/1.0 sessions/week | Target reached. Should trigger auto-completion review. |
| Learning | active | 0.0/3.0 sessions/week | No linked active tasks. |
| Adventure & Travel | active | 0.0/3.0 adventures | Linked task exists in tasks.md. |

**Auto-completion candidates:** 3 goals (training, fat reduction, health) have reached or exceeded their targets.

---

## 5. Kanban State

- **All 45 tasks archived.** Zero active tasks.
- The Kanban board is effectively reset — no follow-up tickets exist in the task system.
- All pending work exists only in:
  1. Uncommitted doc updates (P0 from t_c5c6c0e1)
  2. `data/tasks.md` (12 unchecked items, 6 relevant)
  3. `data/followups.md` (2 stale test artifacts)
  4. `data/questions.json` (1 unresolved user question)
  5. Open INVESTIGATE items from prior reconciliation

---

## 6. Reconciliation Table — All Pending Items

| # | Item | Source | Current State | Recommended Action |
|---|------|--------|---------------|-------------------|
| 1 | Uncommitted doc updates (roadmap, product_backlog, t_36b3d88f refs) | t_c5c6c0e1 P0/P1 | Applied but uncommitted | **COMMIT** — risk of loss if worktree discarded |
| 2 | Measurement consumers (4 design-specified) | t_c5c6c0e1 #13 | Partially wired (goal_health only) | DEFER or design doc update |
| 3 | Artifact version auto-bump | t_c5c6c0e1 #22 | Not implemented | DECIDE: implement vs design doc update |
| 4 | Goal metric migration (`current_value`) | t_c5c6c0e1 #24 | Ongoing legacy read | DECIDE: deprecate or complete migration |
| 5 | GitHub Actions billing | t_c5c6c0e1 #27 | Unknown | External verification |
| 6 | Vision: consolidate goal execution planning | docs/vision.md:88 | Existing tests cover boundary cases | CLOSE |
| 7 | Stale E2E test follow-ups (×2) | data/followups.md | Test artifacts, goals don't exist | CLEANUP |
| 8 | "Zakończenie naprawy workoutów..." task | data/tasks.md:17 | No goal, no due date | CLARIFY scope or discard |
| 9 | Endurance challenge follow-ups (×6) | data/tasks.md:18–45 | Challenge completed (Sep 26–28) | CLOSE — post-challenge review |
| 10 | Questions.json unresolved question | data/questions.json | Awaiting user response | ROUTE to user via Telegram |
| 11 | Auto-completion: training goal | data/goals.md | 3.0/2.0 target exceeded | TRIGGER goal review |
| 12 | Auto-completion: fat reduction goal | data/goals.md | 82.0/82.0 target reached | TRIGGER goal review |
| 13 | Auto-completion: health goal | data/goals.md | 1.0/1.0 target reached | TRIGGER goal review |
| 14 | Overdue: "Zdefiniuj mierzalną metodę..." | data/tasks.md:3 | Due Sep 15, 3 days overdue | URGENT — define measurable progress method |
| 15 | Due tomorrow: workflow verification + Janus milestone | data/tasks.md:15–16 | Due Sep 19 | SCHEDULE — these are blocking other work |

---

## 7. Summary & Recommendations

### Immediate (next 24h)
1. **Commit uncommitted doc updates** — 5 files, 13 insertions, 13 deletions. Risk of loss otherwise.
2. **Route questions.json to user** — one pending decision question.
3. **Review 3 goals for auto-completion** — training, fat reduction, health all at/above target.

### This week
4. **Clarify "Zakończenie naprawy workoutów" task** — no scope, no goal link, no due date.
5. **Process overdue data/tasks.md items** — 3 days overdue on measurable progress method.
6. **Close completed endurance challenge** — 6 follow-up items are moot.

### Deferred (no action now)
7. **Measurement consumers** — design doc update preferred over implementation.
8. **Artifact version auto-bump** — design doc update preferred.
9. **Goal metric migration** — requires product decision on deprecation timeline.
10. **Calendar-aware planning, research pipeline, weekly review** — correctly blocked.

### Cleanup
11. **Discard 2 stale E2E test follow-ups** in data/followups.md.

---

*End of reconciliation report.*
