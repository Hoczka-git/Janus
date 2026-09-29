# Triage Decision — Task t_f1e900e7 Specification Conflict

**Triage task:** t_978afa11  
**Date:** 2026-09-30  
**Status:** Decision recorded — implementation work complete via child tasks

---

## 1. The Conflict

Task t_f1e900e7 (Implement Phase D — Agency-Aware Planning) was blocked on three scope questions. The core specification conflict:

| Source | Position |
|--------|----------|
| `docs/janus-agency-first-development-phase.md` §13.5 | Proposes `execution_mode` (USER/JANUS/COLLABORATIVE) + `support_mode` (EXPLAIN/COACH/SCAFFOLD/REVIEW/EXECUTE). Planner chooses least substitutive mode that enables progress. |
| `docs/triage_architectural_roadmap_next_phase.md` §5.1 + P3-2 | **Recommends NOT adding `execution_mode` as a domain concept yet.** The USER/JANUS/COLLABORATIVE distinction is already implicit in who invokes the service (CLI vs Hermes dispatch) and what gates apply. P3-2: "Add only if there's a concrete need for mode-specific behavior (permissions, UI, audit)." |

The design doc says implement it. The triage doc says don't add it as a domain concept yet. Two documents, opposite recommendations.

---

## 2. What Actually Happened

Despite the triage recommendation, the Phase D implementation proceeded through child tasks and is now merged:

- **PR #274** (parent t_86046565, approved round 3): Added `execution_mode.py`, `support_mode.py`, `task_agency.py`, `agency_planning.py`, wiring into `derive_next_action` / `recommend_tasks`. 52 agency tests, 2984 total. Merged.
- **PR #280** (parent t_62758b79, completed): Integrated mode selection with Phase A/C interfaces. 62 agency tests, 2994 total. Merged.

Both parents are finalized. The code exists on `master`. The models and service are real, tested, and wired.

---

## 3. Which Document Takes Precedence

**The design doc takes precedence for this task.** Reasoning:

1. The triage doc's §5.1 recommendation is framed as "Don't add `execution_mode` as a domain concept **yet**" and P3-2 as "Add **only if there's a concrete need**." This is a deferral recommendation, not a prohibition. It explicitly leaves room for later implementation when a concrete need exists.

2. The design doc (`janus-agency-first-development-phase.md`) is the phase-level specification that `docs/roadmap.md` references and that the Agency-First development phase is built from. When two documents conflict on a phase's scope, the phase specification (design doc) is the more specific and more recent artifact for that phase's implementation decisions.

3. The triage doc itself (§6.3, item 5) lists Phase D (agency-aware execution/support modes) as step 5 in the implementation sequence, **after** Evidence (P1-1), Curation gate (P1-2), and Goal-level review (P1-3). This means the triage doc does not oppose Phase D — it sequences it later. The conflict is about timing, not about whether Phase D should exist.

4. The implementation chose to pull Phase D forward. That is a valid planning decision. The triage doc's "not yet" was advisory; the implementation team exercised judgment to proceed.

**Conclusion:** The design doc wins. Phase D implementation is in scope for t_f1e900e7. The triage doc's recommendation is noted but overruled by the more specific phase specification and by the implementation team's judgment that a concrete need exists (agency-aware planning requires mode selection to function).

---

## 4. The Three Block Questions — Resolved

### Q1: Taxonomy implementation yes/no?

**Yes.** Implement the taxonomy as proposed in the design doc. `execution_mode` (USER/JANUS/COLLABORATIVE) and `support_mode` (EXPLAIN/COACH/SCAFFOLD/REVIEW/EXECUTE) are in scope. They are already implemented and merged — see PRs #274, #280. The implementation is not speculative; it exists.

The triage doc's concern (§5.1) that the distinction is "already implicit" is valid as an observation but does not block formalization. Formal enums + a selection rule make the implicit explicit, which is the point of Phase D.

### Q2: Should the "least substitutive mode" selection logic be implemented now or stubbed?

**Implemented.** The selection logic is the core of Phase D. It is already implemented in `agency_planning.py` (`select_execution_mode`, `select_support_mode`) with priority-ordered classification tables. 62 agency tests cover it. Do not stub — the logic exists and is tested.

### Q3: Should the design doc on feature branch t_57e1acdc be merged into this worktree first?

**Not applicable / already resolved.** The design doc referenced in `docs/roadmap.md` is `docs/janus-agency-first-development-phase.md` (the phase specification), not a separate design doc on branch t_57e1acdc. The actual implementation design was done inline in the implementation PRs. The code is merged. No separate design-doc merge is needed.

If t_57e1acdc holds a more detailed design document that differs from what was implemented, that is a documentation discrepancy to resolve separately — not a blocker for t_f1e900e7.

---

## 5. What This Means for t_f1e900e7

- **Scope is clear:** Implement Phase D with execution_mode + support_mode taxonomy and least-substitutive-mode selection logic, integrated with Phase A (next-action engine) and Phase C (PersonalState).
- **Implementation status:** Done. Merged via PRs #274 and #280. Parents t_86046565 and t_62758b79 finalized.
- **Block reason is resolved:** The specification conflict is resolved by giving precedence to the design doc. The triage doc's deferral recommendation is acknowledged but does not block this phase.
- **t_f1e900e7 itself:** The task body says "Implementation not yet started" but the implementation was completed through its child tasks. If t_f1e900e7 is the root coordination task, it can be marked complete now that its children are finalized. If it still has remaining implementation work not covered by the children, that work should be re-scoped explicitly — but the specification conflict is no longer the blocker.

---

## 6. Consistency with Finalized Parents

The decision is consistent with the finalized parents:

- **t_86046565** (review/verify): Approved the implementation with 3 rounds of review. Confirmed wiring, dead-code elimination, and test coverage.
- **t_62758b79** (integration): Completed integration with Phase A/C. Confirmed end-to-end planning cycle works.

Both parents treated the taxonomy as in-scope and validated it. This triage decision aligns with their outcome.

---

## 7. Caveats / Follow-Up

1. **Documentation alignment:** `docs/triage_architectural_roadmap_next_phase.md` §5.1 and P3-2 should be updated to reflect that Phase D was implemented and merged, so the triage doc does not continue to recommend against something that exists. This is a documentation task, not a code task.

2. **Design doc vs implementation drift:** If branch t_57e1acdc holds a design doc that differs from the merged implementation, that discrepancy should be reconciled in a documentation task. The implementation is the source of truth for what was built.

3. **Triage doc sequencing:** The triage doc placed Phase D after Evidence, Curation gate, and Goal-level review. If that sequencing matters for architectural reasons (e.g., Phase D should consume Evidence records), verify that the implementation does not depend on Evidence being in place. From the parent task metadata, the implementation consumes PersonalState (Phase C) and wires into the planning flow (Phase A). It does not appear to depend on Evidence (Phase B). If it does, that is a hidden dependency to flag.

---

*End of decision.*
