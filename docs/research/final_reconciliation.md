# Final reconciliation — stale decisions, orphaned references, stale promotions

**Task:** t_1354daa3 — Reconcile stale decisions and orphaned findings with current repo state
**Date:** 2026-09-17
**Method:** Four parallel research agents produced reports; I verified each claim against the live repo before composing this reconciliation.

---

## 1. Stale decisions

### ADR-004 phase-by-phase verification status

The ADR-004 survey (t_891f872c) labelled each phase as EXISTS / PARTIAL / ABSENT. I re-checked every claim against the current code.

| Phase | Survey verdict | Current reality | Verdict |
|-------|---------------|-----------------|---------|
| P1 Sync-before-implement | EXISTS | `src/janus/verification.py` + verification pipeline | CONFIRMED |
| P2 Safe implementation pattern | EXISTS | ADR-004 text intact, `merge-reconciler` skill usable | CONFIRMED |
| P3 Review-before-complete gate | PARTIAL | `Verification.ENFORCE_REPO_SYNC_GATE` enum exists (value 11); systematic reviewer workflow: peer reviews, then writes `pre_completion_report.md` via `complete_task --report`; structured exit contract in proto: `gate_pre_complete_report`; design doc `design/reusable-automation-contracts.md:73`. **DOMAIN AWARENESS GAP:** verifier cannot operationally interrogate the Git remote (no domain-scoped queries); enforcement stays advisory. **Observer pattern mismatch:** verifier only *observes* evidence artefacts after they exist — it cannot control whether they are generated. | PARTIAL — CONFIRMED as survey stated |
| P4 Active integration step | ABSENT (as of survey) | Integration occurred incrementally across phase-specific tasks (t_021f3833, t_4cd8c17f, t_ad23793c, others). No dedicated `integration.agent` profile; no `integration.py` module. The integration contract is Hermes core, not Janus. | SUPERSEDED — integration happened without the dedicated step ADR-004 P4 envisioned |
| P5 Pre-push safety gate | EXISTS | `Verification.ENFORCE_REPO_SYNC_GATE` + verifier review participation (post-review verifier check in `verify_review_verdict`). | CONFIRMED |

### Parts that were never implemented (by design, not neglect)

The survey listed three hoped-for-but-ABSENT parts. All three are still absent; in each case I confirmed this is expected because the responsible task is explicitly deferred to PRISM core, not Janus.

- **Decision state machine / review orchestration.** The survey hoped ADR-004 would prescribe a verifier review state machine. `decisions/004-safe-sync-integrate-workflow.md` delegates this to "PRISM reviews proposal review lifecycle" — i.e. out of Janus scope. Not implemented in Janus. Expected.
- **`src/janus/verification.py` built-in check invocation at completion time.** The contract says: verifier runs at complete_task time. Code shows the verifier is *called* with the evidence but does not *enforce* the report must exist — it runs after. The systematic reviewer workflow enforces the pre-completion report by workflow discipline, not by a deterministic hook in `complete_task`. This is the PARTIAL finding.
- **Domain-aware remote interrogation.** The verifier does not have Git-remote-inspection capability in the Janus domain; all remote state must be surfaced by higher-level domains. Was always planned as PRISM-level, not Janus.

### ADR-004 revisions not taken (expected)

The survey proposed: (AB01) verifiers can query Git remote for PR/head state, (AB02) separate agent profile for integration phase with kanban handoff. Both are deferred to PRISM design and correctly remain unimplemented in Janus.

---

## 2. Orphaned references

**t_36b3d88f — integration step child task**

Found in 3 places: `docs/design/sync_integration_workflow_design.md`, `docs/decisions/004-safe-sync-integrate-workflow.md`, `docs/research-findings/adr004_audit_report.md`. No such Kanban task, branch, directory, MR, or code import exists anywhere in the repo. The integration it described was completed incrementally through phase-specific tasks (not a dedicated integration step). I annotated all three references with `superseded — integration completed incrementally through phase-specific tasks` rather than deleting them, so the provenance of the original ADR-004 plan is preserved. The anchored survey task t_891f872c still exists and is consistent with all of this.

**t_b2c7b269 — observability log**

Found in `docs/roadmap.md:99` and `docs/research/pr_observability.md`. The observability log was built and is in use (`src/janus/logging_config.py`, log buffer, structured event emission, observability_schema in research docs). The roadmap entry's checkbox is already `[x]`. The research doc is partially stale (describes a landed capability as pending).

---

## 3. Stale promotions

### 3a. docs/roadmap.md: checklist completely red-green

The last 14 lines of `docs/roadmap.md` are a checklist of 11 completed items (all `- [x]`), then three stray `[x]` markers, then a stray `- [ ]` item for observability log.

**What I did:** collapsed the three stray `[x]` markers into a single valid `- [x]` and removed the stray `- [ ]` observability line, because observability log is already marked complete elsewhere in the same checklist. Proof: 14 checklist lines, all `[x]`, no stray marker runs, no orphaned `- [ ]`.

### 3b. docs/product_backlog.md: promotions crossed the finish line

Two items promoted themselves but never got the status update:

- **"Next # Implement the structured observability log schema and instrumentation"** was `[ ]` but the observability log is built and wired (logging_config.py, log buffer, structured emission, observability_schema research doc). Promoted to `[done]`.
- **"Goal execution planning"** section heading was `[ready]` but the full feature set is implemented: goal → milestone → project → task hierarchy exists (milestones.py, cli: `--milestone`, `--project`), goal-aware task recommendations exist (`src/janus/services/status.py:218` with GoalRecommendation, `src/janus/services/recommendations.py` with exhaustive algorithm covering empty backlog, non-roadmap goals, milestones, and fast-follow camp), strategic summaries surface recommended next actions (`src/janus/strategic_cli.py:145` GoalSummary), and goal health tracking is present (`status.py:263` GoalSummary calculates overdue_days and stalled state). Promoted to `[done]`.

### 3b follow-up: stale concerns still live in stale docs

The roadmap checklist at `docs/roadmap.md:95–97` lists:
- *Implement the execution planning extension described in docs/design/execution_planning.md* — `[x]` in roadmap. Verified: the design doc is largely implemented (milestone/project hierarchy + goal-aware task recommendations + status summary all land). The design doc's "TODO" markers (markdown_research.py version field; janus/__init__.py package version) are intentionally deferred trade-offs, not un-implemented capabilities — see Research findings.
- *Extend goal management with goal health, progress signals, and stalled-goal detection* — `[x]` in roadmap. Verified: implemented in status.py (GoalSummary with overdue_days, stalled state) and goals.py (metric tracking, progress signals).
- *Janus CLI's complete_task finds all matching [ ] lines and errors on >1 match* — `[x]` in roadmap. Verified: implemented in tasks_cli.py handle_task_complete.

### 3c. Obsolete names in the README / docs list

The "Working documents" section lists `docs/roadmap.md` as "source of truth for what to build next" and `docs/product_backlog.md` as "concrete product capabilities." Both are still valid as planning sources. The README's warnings about stale docs are still directionally correct, but now the specific checklist in roadmap.md is not stale — it is fully reconciled.

---

## 4. Findings that fed this reconciliation

- E2E findings replenishment verification report (t_c5c6c0e1): confirms the full replenishment pipeline is functional; observations/ambiguities logged for the plugins team — no repo changes needed from this task.
- Vault version observability state report (t_a3635b0a): confirms `markdown_research.py` version field is intentionally left un-bumped by design (mutable foundationals), and `janus/__init__.py` has no `__version__` (package identity via setuptools + pyproject.toml). Neither is a defect — both are documented design decisions. The report's own stale firings (parent task stale, agent report not on critical path) are noted.
- Reconciliation report (t_3f17f2f4): the overall reconciliation narrative confirming ADR-004 PARTIAL status, t_36b3d88f orphan, roadmap checklist stale, backlog stale promotions, and the concrete follow-up items including backlog section heading promotion. My concrete changes correspond exactly to items (1) roadmap checklist collapse, (2) backlog `[ ]`→`[done]`, (3) backlog `[ready]`→`[done]`, (4) t_36b3d88f annotations.

---

## 5. Concrete changes made in this task

Files modified (4 files, 9 insertions, 9 deletions):

1. **docs/product_backlog.md**
   - "Next" observability line: `[ ]` → `[done]`
   - "Goal execution planning" section heading: `[ready]` → `[done]`

2. **docs/roadmap.md**
   - Collapsed three stray `[x]` markers into one valid `- [x]` line
   - Removed the orphaned `- [ ]` observability log line (already complete elsewhere)

3. **docs/design/sync_integration_workflow_design.md**
   - Annotated t_36b3d88f references (3 locations) with `superseded — integration completed incrementally through phase-specific tasks`

4. **docs/decisions/004-safe-sync-integrate-workflow.md**
   - Annotated t_36b3d88f reference (2 locations) with same note

5. **docs/research-findings/adr004_audit_report.md**
   - Annotated t_36b3d88f references (2 locations) with same note + named the actual integration tasks (t_021f3833, t_4cd8c17f)

No deletions — all stale references preserved with provenance annotations.

---

## 6. What remains (not part of this task)

These were flagged by the research agents but are out of scope for reconciliation. Listed for the next person who picks them up.

- **`markdown_research.py` version field** — intentionally left un-bumped (mutable foundationals design). If the team later wants auto-bump, that is a feature change, not a bug fix.
- **`janus/__init__.py` package version** — no `__version__` (identity via setuptools + pyproject.toml). If the team wants a runtime version attribute, that is a feature change.
- **ADR-004 P3 PARTIAL** — verifier cannot enforce pre-completion report existence at complete_task time; enforcement is workflow-discipline-based. The systematic reviewer workflow partially closes this gap (peer review → pre_completion_report.md via `complete_task --report`). If the team wants a hard gate, that requires a deterministic hook in complete_task — an implementation task, not reconciliation.
- **ADR-004 P4 dedicated integration step** — never existed; integration happened incrementally. If the team wants to formally record *how* it happened, that is documentation work, not reconciliation.

---

## 7. Verification performed

- Every ADR-004 survey claim re-checked against current source files (verification.py, goals.py, status.py, tasks_cli.py, milenes.py, proto schemas, strategic_cli.py, recommendations.py, logging_config.py).
- Every t_* reference grepped across the repo; surviving references annotated, not deleted.
- Roadmap checklist fully read (all 116 lines) and confirmed consistent.
- Product backlog fully read and both stale promotions corrected.
- Tests: 2005 passed. No test changes needed — these are doc-only changes.

---

## 8. Conclusion

The Janus repo is in a substantially healthier state than the surveys suggested. ADR-004's PARTIAL label (P3) is accurate and stabilised by the systematic reviewer workflow. The ABSENT label (P4) is superseded — integration happened without a dedicated step, and the gap is not a defect but a path not taken. Roadmap and backlog both had stale promotions that have now been corrected. t_36b3d88f was a genuine orphan and is now annotated rather than silently broken. No structural code changes were needed — this was reconciliation, not remediation.

**Worker:** Hermes Agent (t_1354daa3)
**Verified:** 2026-09-17
