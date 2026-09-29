# Outcome Gap Analysis — 2026-09-29

**Task:** t_4391d152 — Detect outcome gaps by comparing task status to metric trends
**Analyzed:** goals.md, tasks.md, metric_history.md
**Method:** Cross-reference completed goals and completed tasks against metric values and trends.

---

## Summary

2 completed goals, 1 OUTCOME GAP detected. 19 completed tasks, several linked to active goals with stagnant or misaligned metrics. Metric history shows 3 tracked metrics with flat or oscillating trends and no corresponding goals in goals.md.

---

## 1. Completed Goals — Metric vs. Target

### ✅ No gap: Complete autumn endurance challenge

| Field | Value |
|-------|-------|
| Status | completed |
| Metric | Zrealizowane wydarzenie (wydarzenie) |
| Start → Current → Target | 0.0 → 1.0 → 1.0 |
| Direction | increase |
| Related tasks completed | 2/2 (Ustal konkretne jesienne wyzwanie..., Przygotuj plan przygotowania...) |

Metric reached target (1.0 = 1.0). Both linked tasks completed. **No gap.**

---

### ⚠️ OUTCOME GAP: Martwy ciąg trap bar

| Field | Value |
|-------|-------|
| Status | **completed** |
| Metric | Osiągnięcie benchmarku (reps/kg) |
| Start → Current → Target | 0.0 → 110.0 → 120.0 |
| Direction | increase |
| Gap | Current 110.0 kg vs target 120.0 kg (91.7% of target) |

**Finding:** Goal marked `completed` but metric is 10 kg short of target. No related tasks are listed on this goal, so completion appears to have been set manually without the metric reaching the defined outcome.

**Suggested next step:** Re-open the goal or adjust the target to reflect the actual achieved value (110 kg), with a new task to close the remaining 10 kg gap. If the benchmark was redefined, document the rationale.

---

## 2. Active Goals — Completed Linked Tasks vs. Metric Movement

### ⚠️ OUTCOME GAP: Career / Engineering

| Field | Value |
|-------|-------|
| Status | active |
| Metric | Kompetencje techniczne rozwinięte (competencies) |
| Start → Current → Target | 0.0 → 0.0 → 3.0 |
| Direction | increase |
| Related task | "Wybierz najważniejsze kompetencje techniczne do opanowania w ciągu 6 miesięcy" |
| Task status | Completed (as "Określ 3-5 konkretnych kompetencji technicznych...") |

**Finding:** The linked task was completed (~2026-09-15) but the metric has not moved from 0.0 in over 2 weeks. The task title differs slightly from the goal's related_tasks entry ("Określ 3-5..." vs "Wybierz najważniejsze..."), which may have prevented automatic metric advancement via `update_goal_progress`.

No metric snapshots exist for this goal in metric_history.md — the metric is tracked only in goals.md current_value, which remains at baseline.

**Suggested next step:** Verify whether the task title mismatch blocked the task_derived metric update. If so, either align the titles or manually advance current_value to reflect completed work. Consider breaking "3 competencies" into incremental milestones with observable metric steps.

---

### 📌 Informational: Learning

| Field | Value |
|-------|-------|
| Status | active |
| Metric | Sesje nauki w tygodniu (sessions/week) |
| Current → Target | 2.0 → 3.0 |
| Related tasks | 3 listed, all still OPEN |
| Completed unrelated task | "Learning: Agentów AI and SRE" |

Metric moved from 0.0 to 2.0 (the goal was presumably created after some learning had already happened). No completed tasks are linked to this goal's related_tasks list, so no task-to-metric advancement is expected. The completed "Agentów AI and SRE" task may represent progress but isn't linked. **No gap, but linkage missing.**

---

### 📌 Informational: Janus / Hermes

| Field | Value |
|-------|-------|
| Status | active |
| Metric | Aktywne dni korzystania z Janusa w tygodniu (days/week) |
| Current → Target | 4.0 → 5.0 |
| Related task | "Rozwój Janusa w kierunku obsługi Goals, progress tracking i periodic review" — OPEN |

Metric at 4.0/5.0 with linked task still open. **No gap** — progress is happening.

---

## 3. Metric History Trend Analysis

metric_history.md contains snapshots for goals **not present** in goals.md, and goals in goals.md with **no snapshots**:

### Metrics with flat trends (no movement over weeks)

| Metric | Values | Last update | Goal in goals.md? |
|--------|--------|-------------|-------------------|
| Savings (PLN) | 5000.0 × 18 snapshots | 2026-09-29 | **No** — orphaned metric |
| Body fat % | 18.0 × 18 snapshots | 2026-09-29 | **No** — but semantically related to "8-tygodniowa redukcja tkanki tłuszczowej" (which tracks Obwód pasa, not body fat) |
| Obwód pasa (cm) | 82.0 × 1 snapshot | 2026-09-17 | Yes — "8-tygodniowa redukcja tkanki tłuszczowej" |

### Metrics with oscillating trends

| Metric | Values | Pattern | Goal in goals.md? |
|--------|--------|---------|-------------------|
| Weight (kg) | 72.0, 76.5, 75.0 (repeated) | Oscillating, task_derived | **No** — orphaned metric |

### Goals with metrics but no snapshots in metric_history.md

All other goals in goals.md (Career/Engineering, Janus/Hermes, Learning, Health & Performance, Adventure & Travel, all PLAN 14 benchmarks, etc.) have **zero snapshots** in metric_history.md. Their current_value is tracked only in goals.md.

---

## 4. Data Integrity Observations

1. **Orphaned metrics in metric_history.md:** Savings, Body fat %, and Weight have extensive snapshot histories but no corresponding goals in goals.md. These may be legacy goals that were removed, or metrics tracked outside the goal system.

2. **Goal-metric mismatch:** "8-tygodniowa redukcja tkanki tłuszczowej" tracks Obwód pasa (cm) but body fat % is also being recorded in metric_history. The body fat metric has been flat at 18.0% for 14+ days while the waist circumference goal shows progress (86→83→target 82).

3. **Snapshot-goal value discrepancy:** The only snapshot for "8-tygodniowa redukcja tkanki tłuszczowej" shows Obwód pasa = 82.0 cm (2026-09-17), but goals.md lists current_value = 83.0 cm. Either the goal wasn't updated after the measurement, or the snapshot recorded a different value than what was persisted.

4. **No metric history for most active goals:** 28 of 31 goals have no snapshots. Metric trend analysis is only possible for 3 goals (and 2 of those don't exist in goals.md).

---

## 5. Consolidated OUTCOME GAP List

| # | Goal | Status | Metric | Gap |
|---|------|--------|--------|-----|
| 1 | Martwy ciąg trap bar | completed | 110/120 kg | Goal completed 10 kg short of target |
| 2 | Career / Engineering | active | 0.0/3.0 competencies | Linked task completed, metric unchanged at baseline for 2+ weeks |
| 3 | 8-tygodniowa redukcja tkanki tłuszczowej | active | 83 cm, target 82 cm (snapshot says 82) | Goal current_value (83) disagrees with latest snapshot (82) |

---

## 6. Recommended Next Steps

1. **Martwy ciąg trap bar:** Decide whether to re-open the goal with a 120 kg target, or formally adjust the target to 110 kg with documentation. Create a follow-up task for the remaining 10 kg gap if re-opening.

2. **Career / Engineering:** Investigate why the completed task didn't advance the metric. Check if the task title mismatch ("Określ 3-5..." vs "Wybierz najważniejsze...") prevented `update_goal_progress` from matching. Manually advance current_value or set up proper task-to-goal linkage.

3. **Metric history cleanup:** Decide whether Savings, Body fat %, and Weight should have corresponding goals in goals.md, or whether the orphaned snapshots should be migrated/annotated.

4. **Snapshot-goal sync:** Resolve the 83 vs 82 cm discrepancy for the waist circumference goal.

5. **Expand metric tracking:** 28/31 goals have no metric snapshots. Consider whether metric_history.md should be the canonical trend store for all metric-bearing goals, or whether goals.md current_value is sufficient for non-time-series metrics.

---

*Report generated from: data/goals.md, data/tasks.md, data/metric_history.md, src/janus/services/goal_progress.py, src/janus/services/goal_health.py, src/janus/models/goal.py*
