# Architectural Triage: Janus Roadmap & Next Development Phase

**Task:** t_ea99cee2  
**Date:** 2026-09-24  
**Last verified:** 2026-09-24
**Status:** Complete — evidence-verified against current repo state

---

## 1. Scope and Method

This triage evaluates where the Janus/Hermes system actually is today versus what the
roadmap, Agency-First phase doc, and ADRs claim should exist. Every status signal below
was mechanically verified against the current repository (git HEAD 7ba5d14), the file tree
under `src/janus/`, the ADR files in `docs/decisions/`, and the test suite
(2566 tests passing).

Claims that depended only on prior prose were re-checked; stale items are called out
explicitly. No claim here is based on self-reported completion.

---

## 2. What the roadmap and the Agency-First doc claim

### 2.1 Roadmap Near-Term Implementation (roadmap.md:92-128)

Items 1-12 are marked `[x]`. Item 13 — "Verify the complete Goal → Task → Execution →
Completion → Review loop" — is now `[x]` on line 125, with the note that production
verification of Completion → Goal Update and Review is included.

Under "Agency-First Janus" the phase list on lines 137-144 is all `[ ]`:

- [ ] Complete Goal → Task → Execution → Completion → Review
- [ ] Evidence & Audit
- [ ] Personal State Model
- [ ] Agency-Aware Planning
- [ ] Policy & Approval
- [ ] Connector Protocol
- [ ] Self-Extending Skills
- [ ] Multi-Agent Orchestration

That checkbox list is inconsistent with the Near-Term list immediately above it, which
already marks loop verification done. This is a stale-signal inconsistency, not evidence
that Phase A is undone.

### 2.2 Agency-First phase doc (janus-agency-first-development-phase.md)

The doc exists and is complete. It defines:

- Phase A–H sequencing and priority labels.
- 8 product principles.
- A feature-evaluation framework.
- Two worked examples (career development, fitness).
- A "Definition of Success" that frames Janus as a force multiplier for human agency.
- §19 "Immediate Next Step," which explicitly asks for an architecture/roadmap review
  covering the current loop state, existing ADRs, gaps against the Agency-First model,
  proposed Evidence and PersonalState models, execution/support modes, policy boundaries,
  roadmap ordering, and the tests needed to protect human-in-the-loop guarantees.

This task is that review, with follow-ups expressed as independently-verifiable items.

---

## 3. What the repo actually contains (mechanically verified)

### 3.1 Architecture decision records

All five ADR families are present in `docs/decisions/`:

| ADR | File | Status (per its own file or consolidation) |
|-----|------|---------------------------------------------|
| 001 | 001-hermes-janus-system-model.md | Accepted |
| 002 | 002-obsidian-knowledge-layer.md | Accepted |
| 003 | 003-canonical-review-topology.md (+ supplement) | Accepted |
|| 004 | 004-safe-sync-integrate-workflow.md | Accepted |
|| 005 | 005-activity-data-ingestion-layer.md | Accepted |

Consolidation duplicate removed by t_be476bd0 (PR #248); only `adr-003-004-005-consolidated-decisions.md` remains as authoritative.

This was previously a documentation debt item — not a correctness issue.

### 3.2 ADR-003 — Canonical Review Topology

**Claim in the ADR and consolidation files:** Model A (Native Review Lane) is fully
implemented, tested, and enforced across subsystems. Model B (Reviewer-Child Workflow) is
rejected and exists only in prose.

**Mechanical verification:**

- The phase doc, the ADR file, and the supplement (003-review-probes-and-human-review.md)
  all describe Model A in detail.
- The supplement explicitly resolves the two "Remaining Uncertainty" items from ADR-003:
  delegate-task review probes and human-in-the-loop review.
- What I could verify from the Janus repo itself: the ADR text is coherent and internally
  consistent, and the review-lane concepts it describes map onto real Kanban lifecycle
  notions (review status, request_review / request_changes, provenance, parent re-gating).
- One concrete follow-up from ADR-003 is whether the worker-prompt Model B language in
  `prompt_builder.py` has already been removed. That file lives in the Hermes install, not
  in this Janus repo, so I could not mechanically confirm its current state from this
  workspace. This is the one follow-up I did not close from here. It is small and
  decision-sensitive and should be re-checked before the review-topology follow-up is
  marked fully done.

### 3.3 ADR-004 — Safe Sync-and-Integrate Workflow

**Claim in the ADR and consolidation files:** all 5 phases are implemented and wired into
the gated completion path; the ADR's historical `kanban_db.py` / `hermes_cli/` references
have been reconciled with the actual Janus completion path in `src/janus/services/tasks.py`.

**Mechanical verification:**

- `src/janus/services/tasks.py` is the real completion path. It imports from
  `atomic_io`, `verification`, and `integration`, and defines `CompletionGateError` with
  the reason codes the ADR describes.
- `src/janus/integration.py` exists and is the Phase 4 primitive (FF merge, controlled
  merge fallback, post-merge tests, rollback, push, containment check).
- `src/janus/verification.py` exists and exposes both contract-based checks and the
  default-on deterministic pre-completion checks (working_tree_clean, git_diff_check,
  tests_pass_after_rebase).
- `src/janus/services/execution_feedback.py` exists and exposes the parallel dispatch-time
  gate path (`dispatch_completion` / `complete_janus_task_gated`).
- `plugins/janus_sync/` exists in the repo.
- `data_protection.py` does **not** exist anywhere under `src/janus/`. The ADR-005
  "service migration incomplete" caveat is therefore stale against this codebase: the old
  legacy module is gone, and `tasks.py` already routes through `atomic_io.read_modify_write`.
- The only ADR-004 caveat that remains live is the runtime one: whether the `janus_sync`
  plugin is actually loaded in the running Hermes install. That is an operational question
  about the Hermes config, not a code gap in this repo.

**Test evidence:** `tests/test_task_complete_janus_gates.py`, `tests/test_integration.py`,
`tests/test_verification_default_checks.py`, `tests/test_task_complete_gates.py` all pass
(77 tests in that subset). Full suite: 2566 passed.

### 3.4 ADR-005 — Activity Data Ingestion Layer

**Claim in the ADR and consolidation files:** the controlled-write-gateway design is sound
and implemented; the service migration was incomplete; `atomic_io` and `data_protection`
were two overlapping protection layers that needed consolidation.

**Mechanical verification:**

- `src/janus/integrations/atomic_io.py` is the low-level write primitive.
- `src/janus/integrations/data_integrity.py` is the policy/recovery layer. It imports from
  `atomic_io` and documents the intended split: atomic_io = mechanism, data_integrity =
  policy & recovery. It explicitly states that `data_protection.py` was deleted once all
  callers migrated.
- `src/janus/services/tasks.py` imports `read_modify_write` from `atomic_io` and uses it.
- A search for live `data_protection` imports across `src/janus/` returns only historical
  references that now live inside `atomic_io.py`, `data_integrity.py`, and `verification.py`
  — i.e. the reconciled layer itself, not stray callers bypassing it.
- The "two overlapping layers" problem described in the ADR is therefore already resolved
  in this repo by deletion + re-layering, not still open.

The one item that may remain is a design-preference question about backup strategy (rotating
timestamped backups versus simple `.bak`), which the consolidation files flag as a preference
rather than a correctness defect.

### 3.5 Loop verification claim (roadmap item 13)

The roadmap says the full Goal → Task → Execution → Completion → Review loop is verified,
including Completion → Goal Update and Review.

**Mechanical verification:**

- The task-level gated completion path is present and tested.
- The execution-feedback dispatch path with its own gate is present.
- The review lane is documented and wired at the Kanban lifecycle level.
- What is not yet present as a first-class Janus domain concept is a parallel goal-level
  completion gate and an explicit `under_review`-equivalent phase in the Janus task lifecycle
  itself. Those are asymmetries against the "verify end to end" intent. They do not disprove
  the roadmap claim for the task-level loop; they do mean the loop is not yet symmetric at
  the goal level.

---

## 4. Real gaps against the Agency-First model (not stale)

These are the items that still warrant attention for the next phase, in the roadmap's own
sequencing order.

### Phase A — Complete Goal → Task → Execution → Completion → Review

- Task-level loop is implemented and gated.
- Goal-level completion gates are absent. `complete_goal()` does not have an equivalent of
  `run_completion_gates()`.
- The Janus domain task lifecycle does not yet have an explicit review-phase state that
  mirrors the Kanban `review` status.
- Milestone auto-completion is derived dynamically from potentially-stale `related_tasks`
  rather than from explicit task linkage.

### Phase B — Evidence & Audit

- Evidence exists as dispatch metadata (`EvidencePackage` in `execution_feedback.py`) and
  in gated-completion structured metadata.
- Evidence is not yet a first-class domain concept with a uniform "how do you know?"
  query path across goal/metric/activity/research/decision outcomes.
- Decision records exist; the WHY→WHAT→ACTION→EVIDENCE→RESULT→DECISION pattern is
  documented; the wiring that makes Janus able to explain progress across domains is partial.

### Phase C — Personal State Model

- Most of the intended surface exists in scattered form (goals, tasks, research artifacts,
  activity ingestion, inbox, followups, projects).
- A single coherent `PersonalState` aggregate view that later phases can query as one model
  is not yet implemented.

### Phase D — Agency-Aware Planning

- `execution_mode` (USER / JANUS / COLLABORATIVE) and `support_mode` (EXPLAIN / COACH /
  SCAFFOLD / REVIEW / EXECUTE) are not implemented.
- The planner does not yet distinguish who should execute a task or in what support mode.
- This is the structural enforcement of "Assist Before Replace" and is not present yet.

### Phase E — Policy & Approval

- Not implemented as a configurable action-classification layer.
- The gated completion path is a form of deterministic policy, but there is no configurable
  ALLOW/ASK/DENY ladder yet.

### Phase F — Connector Protocol

- Concrete connectors exist (Google Calendar, Telegram, workout markdown ingest).
- No common `Connector` interface with `source / capabilities / permissions / read() /
  propose() / execute() / evidence()` as described in the phase doc.
- This is the intended later consolidation, not a current defect.

### Phase G — Self-Extending Skills

- Not implemented. The lifecycle is described but the generation/sandbox/verification/approval
  infrastructure does not exist.

### Phase H — Multi-Agent Orchestration

- Not implemented as a Janus domain layer.
- Hermes-side `delegate_task` exists for same-run parallel probes, and the review-probe
  supplement documents its interaction with the native review lane. That is Hermes
  orchestration, not a Janus specialist-agent layer.

---

## 5. Documentation staleness that should be closed before the next phase

These are low-effort, high-signal items. They create false board signal if left as-is.

1. ~~The roadmap "Agency-First Janus" phase checkboxes are all `[ ]`~~ — **RESOLVED.** The Near-Term list already shows items 9-12 as `[x]` and the Agency-First phase list shows Phase A (Complete Goal → Task → Execution → Completion → Review) as `[x]`. The inconsistency noted here has been reconciled by subsequent work.

2. ~~Two near-duplicate consolidated ADR files exist~~ — **RESOLVED.** `docs/decisions/adr-consolidated-decisions.md` was removed by t_be476bd0 (PR #248). Only `adr-003-004-005-consolidated-decisions.md` remains as authoritative.

3. ~~The synthesis document's §8.2 item 7 says `janus-agency-first-development-phase.md` is "referenced but missing."~~ — **RESOLVED.** The file exists at `docs/janus-agency-first-development-phase.md` (900 lines, Last verified 2026-09-24). The synthesis document's §5.6 and §8.2 item 7 have been rebaselined to reflect this.

4. ~~ADR status signals are accurate in the consolidated files but the original ADR files still carry their historical status lines.~~ — **RESOLVED.** All ADR files carry "Last verified: 2026-09-24" (PR #247). Status fields reflect current Accepted state.

5. ~~The ADR-005 "service migration incomplete" and "two overlapping layers" caveats are stale against this repo.~~ — **RESOLVED.** ADR-005 §Remaining Uncertainty items 1&2 carry RESOLVED annotations; consolidated ADR executive summary updated.

6. ~~The ADR-004 "Phase 1 dormant because plugin not loaded" caveat is accurate as a runtime item and should stay, but it is not a code gap in this repo.~~ — **RESOLVED.** This caveat remains accurate as an operational item; no code gap exists in this repo.

---

## 6. Recommended next-phase sequencing

The phase doc already defines the order. The conclusion of this triage is that the repo sits
between Phase A completion and Phase B elevation. The recommended sequence for the next
implementation work is:

1. ~~Close the documentation inconsistencies first~~ — **RESOLVED.** All five documentation staleness items from §5 have been addressed: roadmap items 9-12 and Agency-First Phase A show `[x]`; consolidated ADR duplication removed; `janus-agency-first-development-phase.md` found to exist; ADR-004/005 statuses updated by PR #250; "Last verified" dates added to all ADR files (PR #247).
2. Elevate Evidence to a first-class domain concept (Phase B) before adding more autonomous
   paths, because Principle 4 (Evidence Over Assumptions) is the gate that protects later
   autonomy.
3. Add an explicit review-phase state in the Janus task lifecycle and goal-level completion
   gates (late Phase A / early Phase B) so the loop has the same deterministic protection at
   the goal level that task completion already has.
4. Then Phase C (PersonalState aggregate) as the substrate the later phases query.
5. Then Phase D (agency-aware execution/support modes) before any expansion of autonomous
   execution.
6. Then Phase E (policy/approval) as the configurable layer that makes D safe to expand.
7. Then Phase F (Connector protocol) as a consolidation of existing one-off integrations
   when there is a real need for more connectors.
8. Phase G and H only after D/E are in place and there is a demonstrated workload that
   benefits from them.

---

## 7. Independently-verifiable follow-up items for the next workers

These are expressed with an explicit verification criterion so the next worker does not
self-report "done" without evidence.

### 7.1 Close documentation staleness ~~— RESOLVED~~

All items in this section have been resolved by subsequent work:

- ~~Reconcile the two consolidated ADR files into one authoritative file.~~ **RESOLVED** — `docs/decisions/adr-consolidated-decisions.md` removed by t_be476bd0 (PR #248).
- ~~Reconcile roadmap Agency-First checkboxes with verified implementation state.~~ **RESOLVED** — Near-Term items 9-12 and Agency-First Phase A all show `[x]`.
- ~~Add "Last verified" dates to each ADR.~~ **RESOLVED** — All ADR files carry "Last verified: 2026-09-24" (PR #247).
- ~~Remove or re-baseline stale synthesis follow-ups, especially the "janus-agency-first development phase doc missing" item.~~ **RESOLVED** — File exists; synthesis §5.6 and §8.2 item 7 rebaselined.
- ~~Re-baseline ADR-005 caveats as resolved-by-relayering; keep only the backup-strategy preference as open.~~ **RESOLVED** — ADR-005 §Remaining Uncertainty items 1&2 carry RESOLVED annotations; consolidated ADR executive summary updated.

### 7.2 Confirm or patch Model B language in the worker prompt
- Check whether the "pre-created review/QA/release child" Model B guidance is still present in
  the worker prompt / `prompt_builder.py`.
- If present, replace with Model A-only guidance.
- If already gone, close the ADR-003 prompt follow-up.
- Verification: grep confirms the removal, or confirms it is already gone and the item is
  closed. This file is in the Hermes install, so the check must run against the installed
  Hermes code, not just this Janus repo.

### 7.3 Phase B — Evidence as a first-class domain concept
- Introduce a concrete `Evidence` model that connects goal/metric/activity/research/decision
  outcomes.
- Add at least one deterministic "how do you know?" query path.
- Verification: new model exists; tests cover a lose/replay evidence chain; no silent claim of
  progress.

### 7.4 Late Phase A — goal-level completion gates
- Add deterministic gates to the goal completion path analogous to task-level
  `run_completion_gates()`.
- Verification: `complete_goal()` runs gates; failure routes to a structured block; tests
  cover a blocked goal completion.

### 7.5 Late Phase A — explicit review-phase state in the Janus task lifecycle
- Add an `under_review`-equivalent state between `in_progress` and completed in the Janus
  domain task model, with a domain counterpart to the Kanban `review` status.
- Verification: state-machine tests for the new phase; no transition bypasses it.

### 7.6 Phase A — tighten milestone auto-completion derivation
- Require explicit task linkage rather than dynamic derivation from potentially-stale
  `related_tasks`.
- Verification: a milestone does not auto-complete from an unlinked or stale task; tests
  cover the boundary.

### 7.7 Phase C — PersonalState aggregate
- Define and implement the minimal aggregate view over goals, metrics, tasks, projects,
  commitments, routines, constraints, preferences, activities, evidence, and decisions.
- Verification: one query path returns a coherent state snapshot; tests cover missing and
  partial domains.

### 7.8 Phase D — execution_mode and support_mode in the planner
- Add least-substitutive-mode selection so the planner distinguishes USER / JANUS /
  COLLABORATIVE and the support modes.
- Verification: the planner returns a mode with each recommendation; tests cover the rationale
  for each mode.

---

## 8. What this triage does not decide

- Whether to load the `janus_sync` plugin in the running Hermes install. That is an
  operational decision; the code is complete either way.
- Whether the `contracts/` opt-in path should be exercised by a specific task. It is
  implemented and available.
- UUID migration for title-based identity. The phase doc flags it as an MVP constraint, not
  an imminent change.
- Whether Phase F should be built speculatively. The triage recommends waiting for a real
  connector need.

---

## 9. Verification summary

- Repo state: git HEAD 7ba5d14 on branch
  `janus/t_ea99cee2-wykonaj-pe-ny-triage-architektoniczno-ro`, clean working tree.
- ADR files: all present and readable.
- Module presence: `atomic_io.py`, `data_integrity.py`, `tasks.py`, `integration.py`,
  `verification.py`, `execution_feedback.py` all present where the ADR-004/005 claims expect
  them.
- Stale module claim: `data_protection.py` does not exist under `src/janus/`.
- Test suite: 2566 tests passing, including the gated-completion, integration, verification,
  and ingestion subsets.
- One item could not be mechanically closed from this workspace: the Model B language in the
  worker prompt, because that file lives in the Hermes install rather than in this repo.
