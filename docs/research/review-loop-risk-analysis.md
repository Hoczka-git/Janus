# Pathological Review-Loop Risk Analysis

**Task:** Analyze whether repeated review → request_changes → re-review cycles pose a genuine pathological-loop risk, and define observability/limit options.
**Scope:** Hermes Agent kanban system — review cycles (review → request_changes → re-review)
**Date:** 2026-08-31
**Source findings:** `docs/research/review-loop-handling-findings.md`

---

## 1. Executive Summary

**Verdict: The risk is real but bounded.** Review cycles CAN spin indefinitely within Hermes — there is no automated circuit breaker. However, the practical risk is lower than it appears because (a) each cycle requires a human-equivalent reviewer to actively re-engage, (b) the `sdlc-review` skill's lens variation provides natural decorrelation, and (c) `max_runtime_seconds` caps individual cycle duration. The primary failure mode is waste (token burn, worker slots) rather than system instability.

**Recommendation:** Preserve unlimited behavior by default, but add lightweight observability (a `review_rounds` counter derived from `changes_requested` events) and an opt-in hard limit (`kanban.review_round_limit`, default NULL/unlimited). This gives operators visibility without changing the default workflow.

---

## 2. What "Unlimited" Means in Practice

### 2.1 The cycle flow

```
Implementer                    Reviewer
    |                              |
    |-- request_review() --------->|  (status: review)
    |                              |-- request_changes(reason)
    |<-- reopen_review_task() -----|  (status: ready/todo)
    |-- claim -> work -> request_review()
    |                              |-- request_changes(reason)
    |<-- reopen_review_task() -----|
    |-- claim -> work -> request_review()
    |                              |-- kanban_complete()
    |                              |  (status: done)
```

### 2.2 Natural caps that DO exist (per-cycle, not per-task)

| Mechanism | What it caps | Does it stop review loops? |
|-----------|-------------|---------------------------|
| `max_runtime_seconds` | Duration of a single worker run (SIGTERM + requeue) | No — task re-queues and re-spawns |
| `dispatch_stale_timeout_seconds` (default 4h) | Reclaims tasks with dead heartbeats | No — only triggers on stale PIDs, not loop count |
| `kanban.review_dispatch` | Whether reviewer workers spawn at all | Yes — but disables ALL review dispatch, not just loops |
| Reviewer patience / human attention | Human reviewers eventually approve or escalate | Yes — but only for human reviewers |
| `max_in_progress_per_profile` | Concurrent workers per profile | No — review and implementer are typically different profiles |

### 2.3 What does NOT exist

- **No `review_rounds` column** on the `tasks` table.
- **No counter** that increments per review cycle.
- **No circuit breaker** that trips after N review cycles.
- **No diagnostic rule** that flags tasks cycling through review.
- **No rate-limit** on re-review frequency.

### 2.4 Conclusion: The loop CAN spin indefinitely

A task can bounce between implementer and reviewer without ever hitting an automated guard. The only automated protections (`consecutive_failures`, `block_recurrences`) explicitly exclude review transitions by design.

---

## 3. Failure Modes and Resource-Waste Scenarios

### 3.1 Token burn

Each review cycle consumes:
- Implementer worker: full task context + rework + handoff summary
- Reviewer worker: full task context + prior run history + skill-guided inspection

For a task that cycles N times, total token cost ≈ N × (implementer_cost + reviewer_cost). With N unbounded, this grows linearly with no natural ceiling.

### 3.2 Worker slot starvation

Review spawns count against `max_spawn` alongside ready tasks. A task stuck in review doesn't consume a ready slot, but each cycle does consume a dispatcher tick and a worker spawn slot for both the reviewer and the implementer. In a busy board, this can marginally reduce throughput for other tasks.

### 3.3 Implementer-reviewer deadlock

If the implementer consistently misinterprets the reviewer's feedback (or the reviewer consistently fails to communicate clearly), the task can oscillate without progress. The `sdlc-review` skill's lens variation (Artifact → Execution → Contract) mitigates this by decorrelating inspection across rounds, but it's a skill-level convention, not a platform guarantee.

### 3.4 No system instability

Unlike block→unblock loops (which can escalate to triage and flood the board), review cycles are bounded by the `review` column's single-task semantics. A stuck review task doesn't cascade — it just wastes tokens and worker slots.

---

## 4. Candidate Mitigations

### Option A: Metrics/Telemetry Only

**What:** Count `changes_requested` events per task and expose the count in diagnostics/CLI output.

**Pros:**
- Zero behavioral change — preserves unlimited by default.
- Minimal implementation cost (events already persisted).
- Enables operators to spot stuck tasks manually.
- Foundation for any future limit.

**Cons:**
- No automated protection — waste continues until human intervenes.
- Requires operator vigilance to be useful.

**Implementation complexity:** LOW. Add a `review_rounds` computed column or dynamic count in `kanban_show` output. Optionally add a diagnostic rule in `kanban_diagnostics.py` that flags tasks with >N `changes_requested` events.

**Preserves unlimited default:** YES.

---

### Option B: Warning Logs at N Iterations

**What:** Emit a warning log (and optionally a `kanban_comment`) when a task's review round count exceeds a threshold.

**Pros:**
- Visible signal without blocking work.
- Can be tuned per-board or globally.
- Low implementation cost.

**Cons:**
- Warning fatigue if threshold is too low.
- No automated action — still relies on human response.
- Logs may be ignored in high-volume boards.

**Implementation complexity:** LOW-MEDIUM. Add a check in `request_review()` or `reopen_review_task()` that counts `changes_requested` events and emits a warning event when count ≥ N.

**Preserves unlimited default:** YES.

---

### Option C: Hard Configurable Threshold with Abort

**What:** Add `kanban.review_round_limit` (default NULL = unlimited). When a task's review round count reaches the limit, auto-block with a `review_loop_detected` outcome.

**Pros:**
- Hard stop on waste.
- Configurable per environment.
- Clear escalation signal.

**Cons:**
- Risk of false positives — some tasks legitimately need 4+ review rounds (complex features, security-sensitive work).
- Adds a new config surface with operational overhead.
- May conflict with the design philosophy that "review is not a block."

**Implementation complexity:** MEDIUM. Requires:
1. A `review_rounds` column or dynamic count.
2. A check in `request_review()` or `reopen_review_task()`.
3. A new config key in `config_defaults.py`.
4. A new event type (`review_loop_detected`).
5. Tests.

**Preserves unlimited default:** YES (if default is NULL).

---

### Option D: Soft Throttle

**What:** After N review cycles, rate-limit re-review (e.g., require a cooldown period before the next `request_review()` is accepted).

**Pros:**
- Slows waste without hard-stopping work.
- Gives time for human intervention or skill adjustment.
- Less disruptive than a hard abort.

**Cons:**
- Adds latency to legitimate re-reviews.
- More complex to implement (cooldown state, timer logic).
- May frustrate operators who want fast iteration.

**Implementation complexity:** MEDIUM-HIGH. Requires cooldown state tracking and a timer-based gate.

**Preserves unlimited default:** YES (if threshold is high or disabled by default).

---

### Option E: No Change

**What:** Keep the current design — review cycles are unlimited by design, and the only guard is human oversight.

**Pros:**
- Zero implementation cost.
- Preserves the deliberate design decision that review cycling is healthy.
- No risk of false positives.

**Cons:**
- No visibility into loop counts.
- No automated protection against waste.
- Operators must manually inspect task history to spot stuck tasks.

**Implementation complexity:** NONE.

**Preserves unlimited default:** YES.

---

## 5. Comparison Matrix

| Option | Visibility | Automated Protection | Implementation Cost | Risk of False Positives | Preserves Unlimited |
|--------|-----------|---------------------|--------------------|------------------------|-------------------|
| A: Metrics only | ✅ | ❌ | LOW | None | ✅ |
| B: Warning logs | ✅ | ❌ | LOW-MEDIUM | Low | ✅ |
| C: Hard threshold | ✅ | ✅ | MEDIUM | Medium | ✅ (if default NULL) |
| D: Soft throttle | ✅ | ⚠️ (slows) | MEDIUM-HIGH | Low-Medium | ✅ |
| E: No change | ❌ | ❌ | NONE | None | ✅ |

---

## 6. Recommendation

### 6.1 Proposed Default Posture

**"Preserve unlimited unless evidence of loops, but add metrics + optional warning threshold."**

Specifically:

1. **Implement Option A (Metrics/Telemetry)** as the foundation:
   - Add a `review_rounds` computed field to `kanban_show` output (count of `changes_requested` events).
   - Add a diagnostic rule in `kanban_diagnostics.py` that flags tasks with >3 `changes_requested` events as `review_stuck_candidate`.

2. **Implement Option B (Warning Logs)** as a low-friction signal:
   - When `review_rounds` ≥ 3, emit a `review_round_warning` event (visible in task history).
   - This is informational only — no blocking.

3. **Defer Option C (Hard Threshold)** until evidence of actual pathological loops emerges:
   - The current design deliberately treats review cycling as healthy.
   - Adding a hard limit without evidence of harm risks false positives and conflicts with the design philosophy.
   - If operators report stuck tasks, add `kanban.review_round_limit` (default NULL) as an opt-in guard.

4. **Reject Option D (Soft Throttle)** for now:
   - The added complexity isn't justified given the current risk level.
   - Revisit if metrics show frequent high-round-count tasks.

### 6.2 Rationale

- **Evidence-first:** The codebase has no evidence of pathological review loops in practice. The `sdlc-review` skill's lens variation provides natural decorrelation. Adding a hard limit without evidence would be premature optimization.
- **Design preservation:** The current design explicitly treats review cycling as healthy. Changing this without evidence would violate the principle of minimal intervention.
- **Operator empowerment:** Metrics + warnings give operators the information they need to intervene without imposing automated restrictions that may not fit all workflows.
- **Future-proofing:** The `review_rounds` counter is a prerequisite for any future limit. Building it now (even without a limit) creates the foundation for evidence-based decisions later.

### 6.3 When to Revisit

Revisit this recommendation if:
- Operators report tasks stuck in review for >5 cycles.
- Metrics show a pattern of high-round-count tasks consuming disproportionate resources.
- The `sdlc-review` skill's lens variation proves insufficient for decorrelation.

---

## 7. Implementation Notes (if Option A+B are approved)

### 7.1 `review_rounds` count

The count can be derived dynamically from `task_events` where `kind = 'changes_requested'` and `task_id = ?`. No schema migration needed.

```python
# In kanban_show or a helper:
review_rounds = conn.execute(
    "SELECT COUNT(*) FROM task_events "
    "WHERE task_id = ? AND kind = 'changes_requested'",
    (task_id,),
).fetchone()[0]
```

### 7.2 Diagnostic rule

Add to `kanban_diagnostics.py`:

```python
def _rule_review_stuck_candidate(task_id: str, conn: sqlite3.Connection) -> Optional[dict]:
    """Flag tasks with >3 changes_requested events as potential review-loop candidates."""
    row = conn.execute(
        "SELECT COUNT(*) as n FROM task_events "
        "WHERE task_id = ? AND kind = 'changes_requested'",
        (task_id,),
    ).fetchone()
    if row and row["n"] > 3:
        return {
            "rule": "review_stuck_candidate",
            "severity": "warning",
            "review_rounds": row["n"],
            "message": f"Task has cycled through review {row['n']} times. "
                       f"Consider human intervention or skill adjustment.",
        }
    return None
```

### 7.3 Warning event

In `reopen_review_task()` (after the `review_reopened` event):

```python
# After emitting review_reopened event:
rounds = conn.execute(
    "SELECT COUNT(*) FROM task_events "
    "WHERE task_id = ? AND kind = 'changes_requested'",
    (task_id,),
).fetchone()[0]
if rounds >= 3:
    _append_event(conn, task_id, "review_round_warning", {
        "review_rounds": rounds,
        "message": f"This task is on review round {rounds}. "
                   f"Consider escalating to a human reviewer.",
    })
```

---

## 8. Remaining Uncertainty

1. **Is the lack of review-loop handling a deliberate final design or a known gap?** The `docs/decisions/003-canonical-review-topology.md:155` notes this as an open question. This analysis confirms it is a known gap, not an oversight.

2. **What's the worst-case cost of unbounded review cycling?** Linear token burn with no natural ceiling. In practice, bounded by reviewer patience and `max_runtime_seconds` per cycle.

3. **Could `consecutive_failures` be repurposed?** No — it tracks worker health (spawn/crash/timeout), not quality. Conflating the two would break the circuit breaker's semantic clarity.

4. **How common are high-round-count tasks in practice?** Unknown — this is the key evidence gap. The recommended metrics will answer this.

---

## 9. Next Step

If the recommended posture (Option A+B) is approved:

1. Add `review_rounds` count to `kanban_show` output.
2. Add `_rule_review_stuck_candidate` diagnostic rule.
3. Add `review_round_warning` event in `reopen_review_task()`.
4. Add tests for the new diagnostic and event.
5. Monitor for evidence of pathological loops before considering Option C.
