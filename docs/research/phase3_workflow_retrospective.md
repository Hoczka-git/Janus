# Phase 3 Workflow Retrospective

**Task:** t_1a5efa07 — Retrospective: harden the Janus multi-agent delivery workflow after Phase 3
**Date:** 2026-08-31
**Author:** researcher (synthesis of t_c6bb2bd7, t_3117f0a2, t_a1c50f71)

---

## Purpose

This retrospective analyzes the execution of Phase 3 (Verification Pipeline) and its close-out. It answers the 8 questions posed in the task body using evidence from three parallel investigations: repository inspection, Kanban history inspection, and profile/doc inspection. It does not modify production code, profile configuration, or Kanban behavior.

---

## 1. Which parts of the multi-agent workflow worked well?

### Observed facts

- **Decomposition graph was correct.** t_1a5efa07 was decomposed into four parallel inspection tasks (t_c6bb2bd7, t_3117f0a2, t_a1c50f71, t_9e30708e) with proper parent-child dependency links. All three inspectors completed before synthesis. The diamond convergence on t_9e30708e is structurally sound.

- **Profile routing was appropriate.** Phase 3 close-out (t_a665778c) used three distinct profiles: researcher (t_27cf102a), implementer (t_b01ff44e), reviewer (t_5dcad317). The adversarial review (t_5dcad317) was assigned to the reviewer profile. This is the intended division of labor.

- **The reviewer caught the critical defect manually.** t_5dcad317 performed an independent clean-checkout inspection of t_b01ff44e's worktree and found that all four Phase 3 deliverables were uncommitted. The reviewer's REJECT comment was the first and only place in the board where the uncommitted state was explicitly named as a blocker. This is the workflow functioning as designed: adversarial review found what the implementer did not surface.

- **The remediation cycle completed.** Root task t_a665778c absorbed the remediation: staged the four deliverables on wt/t_b01ff44e, committed as bf4e182, merged to master, and re-verified (validate_ci.py OK, 417 pytest passed, trees clean). The close-out completed in approximately 33 minutes total.

- **Failure-limit enforcement is live.** The t_a1c50f71 task accumulated 8 prior protocol-violation runs before being re-queued. The dispatcher's failure_limit: 3 and max_in_progress_per_profile: 1 settings are operationally enforced.

- **The test suite is comprehensive.** 18 test files, 417 tests, covering domain models, CLI handlers, integrations, and domain logic. Spot check: test_task_state_progress.py — 67 passed in 0.18s.

- **The verification contract exists.** docs/verification.md defines a clear `uv run pytest tests/` command with exit-code semantics, scope description, and a pre-completion checklist.

### Inference

The multi-agent workflow's core loop — research → implement → review → close — is functional. The reviewer profile's adversarial stance and clean-checkout discipline are the strongest durability control in the system today.

---

## 2. Which failures or near-failures occurred?

### Observed facts

- **F1: Uncommitted worktree submitted for review (Phase 3 close-out).** The implementer (t_b01ff44e) verified deliverables locally (417 tests pass, validate_ci.py OK) and requested review, but the worktree was never committed. The reviewer (t_5dcad317) checked out a clean worktree on t_b01ff44e's branch and found `M .gitignore, ?? .github/, ?? docs/verification.md, ?? scripts/` — all absent from HEAD, all branch refs, and all sibling worktrees. Every shared branch pointed at commit 9f044a2. The reviewer REJECTed the closure.

- **F2: Root task absorbed remediation instead of routing back to implementer.** After the reviewer's REJECT, t_a665778c was already promoted to ready and claimed by run 6. The root task did the commit itself rather than returning t_b01ff44e to the implementer. The reviewer's findings went to metadata, not to a task action. There is no explicit "return to implementer" transition in the board.

- **F3: Implementer metadata claimed changed_files without noting uncommitted state.** t_b01ff44e run 4 metadata claimed `changed_files=[.gitignore, docs/verification.md]` — a self-reported claim that was internally inconsistent with the actual git state. The Kanban DB has no field that records whether files are committed or uncommitted.

- **F4: Two of three retrospective inspector runs crashed with protocol violations.** t_c6bb2bd7 run 7 and t_a1c50f71 run 9 both crashed at 1788170078 (61 seconds after start) with `protocol_violation: true`, exited rc=0 without calling kanban_complete or kanban_block, and were immediately re-claimed as runs 10 and 11. Only t_3117f0a2 (run 8) survived its first run. This is the second occurrence of this pattern in Phase 3 (t_b01ff44e had the same run 3→4 transition, though that one was review_requested→reclaimed rather than a crash).

- **F5: The retrospective t_1a5efa07 was created with no body and no triage step.** Created at 1788169984, edited at 1788169993, decomposed at 1788170017 — all within 33 seconds. The body field is empty in the DB. The decomposition was done by auto-decomposer with no human-written brief. The children started immediately with no triage step. Scope and acceptance criteria are defined only implicitly by child task titles.

- **F6: Implementer retry (run 3 → run 4) happened without narrative.** Run 3 set status=review_requested. Run 4 re-claimed with source_status=review. There is no event explaining why the re-claim happened. The implementer's comment [2] ("WORK COMPLETE") was posted during run 4 but does not mention the re-claim, the prior run's state, or that this is a second attempt.

- **F7: CI workflow is non-functional due to 3 typos in ci.yml.** Despite being committed and merged to master:
  - `runs-on: ubuntu-latest` — wrong key. GitHub Actions expects `runs-on: ubuntu-latest`. With `runs-on`, the runner is not found and the job fails at scheduling.
  - `timeout-minutes: 10` — unknown key. GitHub Actions expects `timeout-minutes`. The key is silently ignored; the job runs with the default timeout (360 minutes).
  - `uses: actions/checkout@v4` — wrong action name. GitHub Actions expects `actions/checkout@v4`. The action is not found; checkout fails and the entire verify job is non-functional.

- **F8: validate_ci.py does not catch the ci.yml typos.** scripts/validate_ci.py checks YAML structural hygiene (valid YAML, required top-level keys, job structure) but does not validate GitHub Actions semantics. It would pass ci.yml as structurally valid despite the three runtime-breaking typos.

- **F9: documentation has a cosmetic typo.** docs/verification.md line 22: "dedicated" is misspelled as "dedicated".

- **F10: F-03 (FrozenInstanceError) remains in committed code.** src/janus/verification.py:319, in `_parse_forbidden_symbols`, constructs a frozen `ForbiddenSymbolEntry()` then mutates its fields, raising FrozenInstanceError. 22 of 23 Phase 3.5 scenarios are blocked by F-03 at contract load time. Per frozen scope, it was not fixed in Phase 3.5. Phase 3.5 tests exist (tests/test_verification_phase3_5.py) but are not merged to baseline. F-04 adversarial discovery (t_05e5b18e) completed with 0 defects found — the adversarial review did not catch F-03.

### Inference

The most operationally significant failure is F1+F2: the core durability gate (commit before review) failed, and the remediation path was the root task absorbing the work rather than routing back through the implementer. The CI typos (F7) mean the CI gate that is supposed to protect master is not actually running — every push to master currently bypasses automated verification. F10 means a known bug is in the committed baseline with tests that exercise it sitting outside the merged tree.

---

## 3. Why was the uncommitted-worktree problem not caught before the reviewer?

### Observed facts

- The Kanban DB records task status, comments, events, and run metadata — but it does not record git state. There is no field that says "these files are uncommitted."
- The implementer's worktree had the files on disk. The implementer's comment said "locally verified" — meaning verification happened only in the working tree, not against a commit.
- The `git status` output was not included in the comment or metadata.
- The researcher's worktree (t_27cf102a) was checked out before implementation and could not see the implementer's uncommitted state.
- The root worktree (master) had none of the Phase 3 deliverables before bf4e182.
- The Kanban board transitioned t_b01ff44e to review_requested based on the implementer's self-report, without checking git status.
- The reviewer caught it by checking out a clean worktree and running `git status` — a manual step, not an automated gate.

### Root-cause analysis

The uncommitted-worktree problem was not caught before the reviewer for three reinforcing reasons:

1. **No mechanical durability gate between implementer completion and review dispatch.** The workflow trusts the implementer's self-report that work is done and durable. The kanban_request_review call carries summary + metadata but no git-state attestation. The board accepts the transition based on the call, not on an independent verification of commit state.

2. **The implementer's verification was local-only.** "417 tests pass, validate_ci.py OK" was verified in the working tree. Local verification is necessary but not sufficient for durability — it proves the code works, not that it is persisted. The implementer's metadata claimed changed_files without distinguishing committed from uncommitted.

3. **The reviewer's clean-checkout discipline is the only durability check that caught it.** The reviewer profile's "Repository Reality Before Reports" section (SOUL.md lines 81-103) instructs an independent git checkout-and-inspect. This is the right behavior, but it is a human step in the reviewer's workflow, not an automated gate that runs before review is dispatched. The system relies on the reviewer remembering and choosing to do this.

### Inference

The gap is architectural: durability is verified by the reviewer's discipline, not by a gate that runs before the implementer can request review. The implementer has no structured incentive or requirement to attest to commit state, and the board has no way to verify it independently.

---

## 4. Which responsibilities should belong to: implementer, reviewer, researcher, Kanban/workflow infrastructure?

### Observed facts

- Researcher profile SOUL.md (325 lines) has the most explicit durability and completion guidance: Kanban Completion Protocol, Final Verification checklist, Research Artifacts section, Evidence hierarchy, Run Recovery, Scope discipline, Existing Capability Discovery.
- Implementer SOUL.md (107 lines) names "Hand off for review" as the final step but does not define the handoff evidence shape.
- Reviewer SOUL.md (103 lines) covers adversarial stance, repo-before-reports checklist, and requires a verdict + terminal Kanban action — but the SOUL.md ends at line 103 (mid "git branch") with no verdict section. Verdict guidance lives in the sdlc-review skill.
- config.yaml has kanban.review_dispatch: true, kanban.auto_decompose: true, kanban.failure_limit: 3, kanban.max_in_progress_per_profile: 1 — but these are not mentioned in any profile SOUL.md.
- The sdlc-review skill is the operational review-handoff guide with three lenses (artifact/execution/contract), acceptance-criteria mapping, and a verification checklist before verdict.
- No consolidated multi-agent hand-off contract document exists.
- No shared durability-checklist template exists across profiles.

### Recommendation: responsibility assignment

**Implementer:**
- Must attest to commit state in handoff metadata — explicitly state whether changes are committed, and if not, why. This is the single highest-value implementer-side change.
- Must include in handoff metadata: changed file list, verification command run and its output/exit code, artifact paths, which acceptance criteria were satisfied, and what remains uncertain.
- Must not request review on uncommitted changes unless the task body explicitly allows it (e.g., a documentation typo fix where the reviewer can apply it directly).

**Reviewer:**
- Must perform clean-checkout inspection before every verdict — this is already instructed and is the correct behavior. The gap is that it is not enforced mechanically.
- Must produce a verdict that cites specific evidence (file paths, command output, git state) — currently guided by sdlc-review skill but not stated in reviewer SOUL.md.
- Must route findings to a task action (request_changes or block) rather than only to metadata, so the board state reflects the finding.

**Researcher:**
- Already has the strongest durability guidance. The gap is cross-profile handoff: when research feeds implementation or review, the researcher should specify what evidence the downstream profile should expect. Currently the "Request Follow-Up" section points work to another profile but does not specify the handoff shape.
- Synthesis tasks (like t_9e30708e) should produce findings that are directly usable as input to implementation decisions — currently the format is good but the handoff contract to the downstream task is implicit.

**Kanban/workflow infrastructure:**
- Could mechanically verify commit state before allowing review_requested transition — e.g., a hook or check that confirms the implementer's worktree is clean or that changed_files are committed. This is the highest-leverage infrastructure change.
- Could surface the operational config (review_dispatch, failure_limit, max_in_progress) in the profile SOUL.md files or a shared workflow doc so workers understand the enforcement model.
- Could require structured handoff metadata (not just free-form summary) for review_requested transitions.

---

## 5. Are the current profile descriptions and SOUL.md instructions sufficient?

### Observed facts

- Researcher SOUL.md is comprehensive and sufficient for research tasks. The Final Verification checklist, Research Artifacts section, and Completion Protocol cover the durability and completion questions well.
- Implementer SOUL.md is insufficient for the handoff step: it names "Hand off for review" but does not define what the handoff must contain. The durability principle is stated ("provide concrete evidence that the result is durable and works") but not operationalized into a checklist.
- Reviewer SOUL.md is thinner than the operational expectations. It ends at line 103 with no verdict section. The verdict guidance (approve / request changes / escalate, what the summary must cite) lives in the sdlc-review skill, not in the profile doc. A reviewer reading only the SOUL.md would not find the verdict standard.
- No profile SOUL.md mentions that review_dispatch is automated (config.yaml line 135) or how failure_limit behaves. This is operational knowledge that currently lives only in config.
- Completion criteria are task-dependent (task body acceptance criteria) rather than profiled. Researcher is closest to a profiled standard via its Final Verification checklist. Implementer and reviewer rely on the task + sdlc-review skill.

### Root-cause analysis

The instructions are sufficient in aggregate but uneven in distribution. The researcher profile carries the durability torch; the implementer and reviewer profiles have gaps that are filled by the sdlc-review skill rather than by the profile docs themselves. This means a worker who reads only their profile SOUL.md has an incomplete picture of the handoff and verdict expectations. The operational enforcement (failure_limit, review_dispatch) is invisible to someone who reads only the profile docs.

### Inference

The profiles are not insufficient in a way that caused the Phase 3 failures — the reviewer's SOUL.md discipline caught the defect. But they are uneven, and the unevenness means the durability guarantees are stronger in some profiles than others. The implementer gap (no handoff evidence spec) is the most likely contributor to F1: the implementer was not instructed to attest to commit state, so they did not.

---

## 6. Should task completion require explicit durability checks?

### Answer: Yes, with profile-specific scope.

### Reasoning

The Phase 3 close-out failure (F1) is direct evidence that local verification without commit-state attestation is not sufficient for durability. The implementer verified 417 tests pass locally — that was true. The problem was not that verification was skipped; it was that verification was local-only and the commit state was not attested.

The researcher profile already requires this (Final Verification checklist: "Did I create any required durable artifact?", "Did I verify the artifact actually exists?"). The implementer and reviewer profiles should have equivalent explicit checks, scaled to their role:

- **Implementer durability check:** Are the changed files committed? (If not, why?) Was the verification command run against the committed state or only the working tree? What is the exit code and how was it obtained?
- **Reviewer durability check:** Did I inspect the actual git state (clean checkout, git status, git diff) or only the handoff metadata? Does the repository state match the claimed state?
- **Researcher durability check:** Already present. Strongest of the three.

### Inference

Explicit durability checks are necessary and the researcher profile shows they are tractable. The gap is that they are not required of implementer and reviewer in the same structured way. The Phase 3 failure would likely have been caught earlier if the implementer's handoff metadata had required a commit-state attestation field.

---

## 7. Should review handoff require structured evidence?

### Answer: Yes.

### Reasoning

The current handoff is free-form summary + metadata. The implementer's t_b01ff44e metadata claimed `changed_files=[.gitignore, docs/verification.md]` without noting uncommitted state. A structured handoff that required specific fields — particularly a commit-state attestation — would have made the uncommitted state visible at handoff time rather than only at review time.

Structured evidence does not replace the reviewer's independent inspection (that is still required and is the stronger check). It adds a layer: the implementer attests to specific facts, and the reviewer verifies them. The attestation makes missing information visible as missing rather than invisible.

### What structured handoff should include (minimum)

1. **Commit state:** Are changes committed? Branch? Commit SHA if committed. If uncommitted, explicit statement and reason.
2. **Verification command:** Exact command run, exit code, how obtained (working tree vs committed).
3. **Changed files:** List with status (committed/uncommitted).
4. **Artifacts produced:** Paths and whether they exist on disk.
5. **Acceptance criteria satisfied:** Which ones, with evidence.
6. **What remains uncertain:** Explicit uncertainties, if any.

### Inference

Structured handoff evidence is a low-cost, high-value change. It does not require new infrastructure — it is a documentation and instruction change to the implementer SOUL.md and possibly a metadata shape convention. The cost is that implementers must fill in more fields, but this is offset by fewer review cycles lost to discoverable-but-unspoken state.

---

## 8. Which process improvements would provide the highest reliability gain with minimal complexity?

### Recommendations

#### R1: Require implementer commit-state attestation in handoff metadata

- **Problem addressed:** F1, F3 — implementer submitted uncommitted work for review and metadata did not surface the uncommitted state.
- **Proposed change:** Add to implementer SOUL.md a requirement that handoff metadata include an explicit commit-state field: committed (with SHA) or uncommitted (with reason). Add a durability checklist item: "Confirm changes are committed before requesting review, or explicitly document why they are not."
- **Expected benefit:** Makes uncommitted state visible at handoff time. Reviewers see the attestation and can act on it before dispatching review. Reduces the chance that a reviewer wastes time on an uncommitted worktree.
- **Implementation cost:** Low. Documentation change to implementer SOUL.md. Possibly a convention for metadata shape. No code or infrastructure change.
- **Priority:** High. This is the single change most directly connected to the Phase 3 failure.

#### R2: Add GitHub Actions semantics validation to validate_ci.py (or supplement it)

- **Problem addressed:** F7, F8 — ci.yml has 3 typos that make the verify job non-functional, and validate_ci.py does not catch them.
- **Proposed change:** Extend validate_ci.py to check GitHub Actions semantics: `runs-on` must be a valid runner label (e.g., ubuntu-latest), `timeout-minutes` must be the correct key, `uses` references must be known action names or at least well-formed (owner/repo@version). Alternatively, add a separate lightweight check that runs `actionlint` if available, or a minimal allowlist of known-correct action references.
- **Expected benefit:** The CI gate that protects master would actually be verifiable. The typos would be caught before merge.
- **Implementation cost:** Low to medium. validate_ci.py is already in the repo. Extending it to check known action names and runner labels is a small addition. Using actionlint would require adding it as a dependency or CI step.
- **Priority:** High. A non-functional CI gate is a significant reliability hole. Every push to master currently bypasses automated verification.

#### R3: Fix the 3 ci.yml typos

- **Problem addressed:** F7 — ci.yml is non-functional.
- **Proposed change:** Change `runs-on` to `runs-on`, `timeout-minutes` to `timeout-minutes`, `actions/checkout@v4` to `actions/checkout@v4`. These are literal typo fixes.
- **Expected benefit:** CI verify job becomes functional. Automated verification runs on push/PR.
- **Implementation cost:** Trivial. Three one-word changes in one file.
- **Priority:** High. This is the immediate fix for F7. Note: this is an implementation task, not a documentation task — it modifies production code (.github/workflows/ci.yml). Recommend creating a dedicated implementation task for this rather than fixing it in this retrospective.

#### R4: Fix the documentation typo in verification.md

- **Problem addressed:** F9 — "dedicated" is misspelled.
- **Proposed change:** Fix the typo.
- **Expected benefit:** Cosmetic. Low impact on durability.
- **Implementation cost:** Trivial.
- **Priority:** Low. This is a documentation typo. Recommend bundling with R3 in the same implementation task if one is created, since both are trivial fixes. Note: this modifies production code (docs/verification.md). Recommend an implementation task.

#### R5: Address F-03 (FrozenInstanceError) in verification.py:319

- **Problem addressed:** F10 — known bug in committed baseline, 22/23 Phase 3.5 scenarios blocked, tests exist but are not merged.
- **Proposed change:** Fix `_parse_forbidden_symbols` to not mutate a frozen instance. Merge the existing Phase 3.5 tests (tests/test_verification_phase3_5.py) to baseline. This is scoped outside Phase 3.5's frozen scope, so it is a separate remediation task.
- **Expected benefit:** Removes a known defect from the committed baseline. Unblocks Phase 3.5 scenarios.
- **Implementation cost:** Medium. Requires understanding the FrozenInstanceError pattern in verification.py, fixing the mutation, and merging the Phase 3.5 tests. The tests already exist; the fix is in src/janus/verification.py.
- **Priority:** Medium. This is a known bug in the committed baseline. It is not a process issue — it is a code issue. Recommend creating a dedicated implementation task. Note: this modifies production code (src/janus/verification.py). Not in scope for this retrospective to fix; recommend an implementation task.

#### R6: Add a short "verdict" section to reviewer SOUL.md

- **Problem addressed:** Gap noted in t_a1c50f71 — reviewer SOUL.md ends at line 103 with no verdict section; verdict guidance lives in sdlc-review skill.
- **Proposed change:** Add a short section to reviewer SOUL.md that states the verdict options (approve / request changes / block), what evidence the summary must cite, and that the terminal Kanban action is required. This does not need to duplicate the sdlc-review skill; it needs to point to it and state the minimum bar.
- **Expected benefit:** Reviewer profile is self-contained for the core verdict question. Reduces reliance on an external skill for the most important reviewer decision.
- **Implementation cost:** Low. Documentation change to reviewer SOUL.md.
- **Priority:** Medium. The reviewer caught the Phase 3 defect despite this gap, so it is not the cause of any failure. But strengthening the reviewer profile reduces reliance on implicit knowledge.

#### R7: Add cross-profile handoff guidance to researcher SOUL.md

- **Problem addressed:** Gap noted in t_a1c50f71 — researcher SOUL.md has no explicit cross-profile handoff section. When research feeds implementation or review, the handoff shape is implicit.
- **Proposed change:** Add a short section to researcher SOUL.md on handoff to implementer/reviewer: what evidence the downstream profile should expect, what shape the follow-up task body should take, and that the researcher's artifact is the durable record.
- **Expected benefit:** Makes researcher→implementer and researcher→reviewer handoffs more consistent. Reduces the chance that a downstream task starts without clear evidence expectations.
- **Implementation cost:** Low. Documentation change to researcher SOUL.md.
- **Priority:** Low to medium. The researcher profile is already the strongest; this is refinement, not a gap that caused a failure.

#### R8: Add a shared durability checklist that all profiles can use

- **Problem addressed:** Gap noted in t_a1c50f71 — no shared durability-checklist template across profiles. Each profile has its own language.
- **Proposed change:** Create a short shared checklist (could be in a docs/ file or a skill) that any profile can run through at completion time: artifact exists and is verified, claims backed by evidence, scope respected, terminal Kanban action taken, commit state attested (for implementer). Researcher already has the closest thing; this would extract the common parts.
- **Expected benefit:** Consistent durability bar across profiles. Reduces the chance that a profile with weaker guidance (implementer, reviewer) misses a durability check.
- **Implementation cost:** Low to medium. A short document or skill section. Adoption is the main cost — profiles would need to reference it.
- **Priority:** Medium. This is a consolidation and standardization improvement, not a fix for a specific failure. Higher cost than R1-R4 for lower immediate reliability gain.

#### R9: Document operational config in profile SOUL.md or a shared workflow doc

- **Problem addressed:** Gap noted in t_a1c50f71 — no profile SOUL.md states that review_dispatch is automated or how failure_limit behaves.
- **Proposed change:** Add a short note to each profile SOUL.md (or a shared workflow doc) stating the operational model: review_dispatch is automated when kanban_request_review is called; failure_limit: 3 means three protocol violations trigger reclaim; max_in_progress_per_profile: 1 means one in-flight task per profile.
- **Expected benefit:** Workers understand the enforcement model without reading config.yaml. Reduces confusion when a task is re-claimed after a protocol violation.
- **Implementation cost:** Low. Documentation change.
- **Priority:** Low. This is operational transparency, not a durability control. The enforcement is already live and working (as demonstrated by t_a1c50f71's 8 prior violations).

#### R10: Require body text on decomposed retrospective/root tasks

- **Problem addressed:** F5 — t_1a5efa07 was decomposed with no body text and no triage step. The scope and acceptance criteria are defined only implicitly by child task titles.
- **Proposed change:** Establish a convention (in the auto-decomposer behavior or in a guideline) that a retrospective or root task should have body text before decomposition, or that decomposition should include a brief in the child task bodies that states the acceptance criteria. If auto-decomposer requires a non-empty body before decomposing, that is a config or behavior change.
- **Expected benefit:** Children start with explicit scope and acceptance criteria rather than implicit ones inferred from titles.
- **Implementation cost:** Medium. Depends on whether this is a config change (auto-decomposer behavior) or a guideline (human responsibility). The auto-decomposer is not inspectable from this workspace.
- **Priority:** Low to medium. This is a process quality improvement. The retrospective still completed despite the missing body, because the child task titles were descriptive enough. But explicit scope is better than implicit.

### Non-recommendations

- **Do not** build a mechanical gate that blocks review_requested unless the worktree is clean. This would be a Kanban behavior change, which the task explicitly excludes ("Do not change Kanban behavior"). It is noted here as the highest-leverage architectural change if the constraint were lifted, but it is out of scope for this retrospective.
- **Do not** modify the existing profile SOUL.md files as part of this retrospective. The task explicitly excludes profile configuration changes. The recommendations above are documentation changes to be implemented in separate tasks if approved.
- **Do not** merge the Phase 3.5 tests or fix F-03 as part of this retrospective. This is production code change, explicitly excluded. Recommend a separate implementation task.

---

## Summary of recommendations by priority

| Priority | Recommendation | Problem | Cost |
|----------|---------------|---------|------|
| High | R1: Implementer commit-state attestation in handoff metadata | F1, F3 | Low — doc change |
| High | R2: Add GitHub Actions semantics validation to validate_ci.py | F7, F8 | Low-medium — script extension |
| High | R3: Fix 3 ci.yml typos (implementation task) | F7 | Trivial — 3 one-word fixes |
| Medium | R5: Fix F-03 FrozenInstanceError + merge Phase 3.5 tests (implementation task) | F10 | Medium — code fix + test merge |
| Medium | R6: Add verdict section to reviewer SOUL.md | Profile gap | Low — doc change |
| Medium | R8: Shared durability checklist across profiles | Profile gap | Low-medium — doc/skill |
| Low-medium | R7: Cross-profile handoff guidance in researcher SOUL.md | Profile gap | Low — doc change |
| Low | R9: Document operational config in profiles | Transparency gap | Low — doc change |
| Low | R10: Require body text on decomposed retrospective tasks | F5 | Medium — behavior/guideline |
| Low | R4: Fix verification.md typo (bundle with R3) | F9 | Trivial — 1 word |

---

## Issues recommended for promotion to implementation tasks

The following are concrete, justified improvements that modify production code or profile configuration. They are out of scope for this discovery/recommendation task but should be promoted to implementation tasks:

1. **Fix ci.yml typos (R3) + fix verification.md typo (R4).** Trivial, high-value. One implementation task. Modifies .github/workflows/ci.yml and docs/verification.md.
2. **Extend validate_ci.py with GitHub Actions semantics checks (R2).** One implementation task. Modifies scripts/validate_ci.py. Should be done before or alongside R3 so the CI gate is verifiable after the typos are fixed.
3. **Fix F-03 FrozenInstanceError and merge Phase 3.5 tests (R5).** One implementation task. Modifies src/janus/verification.py and merges tests/test_verification_phase3_5.py. Separate from the CI work; different risk profile.

The profile documentation changes (R1, R6, R7, R8, R9) are also implementation tasks in the sense that they modify profile SOUL.md files, which the task excludes. If approved, they should be separate tasks assigned to the appropriate profiles (likely researcher for R1, R7, R8; reviewer for R6; any profile for R9).

---

## Appendix A: Evidence sources

- t_c6bb2bd7 repository inspection: workspace at /home/dan11hermes/workspaces/janus/.worktrees/t_c6bb2bd7. Findings: Phase 3 commit bf4e182, 18 test files, 417 tests, 3 ci.yml typos, validate_ci.py coverage gap, verification.md typo.
- t_3117f0a2 Kanban history inspection: phase3_kanban_history_inspection.md in workspace. Findings: REJECT→remediate→commit→re-verify cycle, uncommitted-worktree defect caught by reviewer, implementer metadata inconsistency, retrospective decomposed with no body, 2/3 inspector runs crashed, F-03 present in committed code, F-04 found 0 defects.
- t_a1c50f71 profile/doc inspection: `profile-instruction-inspection-findings.md` in workspace (file later removed as redundant). Findings: researcher SOUL.md strongest on durability; implementer handoff evidence under-specified; reviewer SOUL.md thinner than sdlc-review skill expects; no consolidated handoff contract; completion criteria are task-dependent; operational config not mentioned in profiles.

## Appendix B: What this retrospective did not cover

- The Phase 3.5 F-03 discovery is mentioned as context but was not investigated in depth. The Phase 3.5 tests and findings (tests/test_verification_phase3_5.py, docs/verification_pipeline_phase3_5_report.md [removed as redundant], docs/verification_pipeline_phase3_5_findings.md [removed as redundant]) werenot inspected for this retrospective.
- The auto-decomposer behavior and config are not inspectable from this workspace. R10's implementation cost is therefore uncertain.
- The current root worktree (master) has uncommitted changes from later phases (Phase 5, Phase 6, goal system, Telegram weekly). These were not investigated for this Phase 3 retrospective.

---

*This report is discovery and recommendation only. No production code, profile configuration, or Kanban behavior was modified.*
