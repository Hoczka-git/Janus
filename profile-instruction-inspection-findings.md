# Documentation & Profile Instruction Inspection — Findings

**Task:** t_a1c50f71 — Inspect relevant documentation and profile instructions
**Inspected:** 2026-08-31
**Status:** Completed, no modifications made

---

## Scope

Examine existing documentation and current profile descriptions / SOUL.md instructions
relevant to the multi-agent workflow: implementer, reviewer, researcher, and any
Kanban/workflow infrastructure guidance. Assess what each profile is instructed to do
around durability checks, review handoff evidence, and completion criteria. Record
observed facts about what is covered and what is missing. Do not modify anything.

---

## Profiles inspected

1. `/home/dan11hermes/.hermes/profiles/researcher/SOUL.md` — 325 lines
2. `/home/dan11hermes/.hermes/profiles/implementer/SOUL.md` — 107 lines
3. `/home/dan11hermes/.hermes/profiles/reviewer/SOUL.md` — 103 lines

Plus config and skills that shape the multi-agent workflow:
- `/home/dan11hermes/.hermes/config.yaml` (kanban section)
- `/home/dan11hermes/.hermes/skills/devops/sdlc-review/SKILL.md`
- `/home/dan11hermes/.hermes/SOUL.md` (top-level, minimal)

---

## What is covered

### Researcher — most complete on durability and completion

Strong, explicit coverage:

- **Kanban Completion Protocol** (lines 200-258): explicit complete / block / request-follow-up
  lifecycle with when-to-use guidance for each.
- **Final Verification checklist** (lines 299-313): includes "Did I create any required
  durable artifact?", "Did I verify the artifact actually exists?", "Did I perform an
  explicit terminal Kanban action?" — directly addresses the durability-check and
  completion-criteria concerns.
- **Research Artifacts** (lines 155-169): durable findings should be written to the repo;
  completion requires verifying the artifact actually exists and contains the claimed findings.
- **Evidence hierarchy** (lines 89-113): explicit distinction between evidence, fact,
  inference, hypothesis, recommendation — prevents collapsing "looks done" into "is done".
- **Run Recovery** (lines 260-272): resume from current state; do not assume previous
  summary was persisted.
- **Scope discipline** (lines 276-295): do not implement unless assigned; do not silently
  expand scope.
- **Existing Capability Discovery** (lines 173-196): explicit "does not exist" vs
  "exists but not configured" vs "exists in a different subsystem" distinctions.

Coverage gap noted below.

### Implementer — durability mentioned, handoff evidence under-specified

Covered:

- Core principle: "provide concrete evidence that the result is durable and works" (line 5).
- Core principle: "Prefer correctness and durability over speed or cosmetic completeness" (line 24).
- Workflow ends with "Verify durability" → "Hand off for review" (lines 104-108).
- Repository Inspection section: check whether capability already exists before adding new.
- Task protocol: inspect task, acceptance criteria, parent results, current repo state.

Gap: the "Hand off for review" step is named but the SOUL.md does not define what the
handoff summary/metadata must contain (changed files, verification commands run, artifact
paths, which acceptance criteria were satisfied). Researcher and reviewer both reference
"review handoff metadata", but implementer does not specify its shape.

### Reviewer — adversarial stance, repo-before-reports, handoff metadata inspected

Covered:

- Responsibility: "determine whether assigned work is actually correct, complete, durable,
  and safe to accept" (line 5).
- Independent adversarial stance: search for evidence it is incomplete/incorrect/non-durable/
  insufficiently tested/outside scope (line 15).
- Goal is to find reasons to reject, not to confirm (lines 34-37).
- Task protocol: inspect task, acceptance criteria, parent results, comments, review handoff
  metadata, then independently inspect repo state (lines 62-73).
- "Repository Reality Before Reports" section (lines 81-103): git status, git diff,
  git diff --cached, git log, git show, git branch — explicit checkout-and-inspect checklist.
- Explicit review verdict + terminal Kanban action required (line 72-73).

Gap: the SOUL.md itself ends at line 103 (mid "git branch"), so the profile doc does not
contain a "how to produce a verdict / what evidence the summary must cite" section.
That guidance currently lives in the sdlc-review skill rather than in the profile SOUL.md.

### Workflow infrastructure — review dispatch and failure semantics are configured

- `kanban.review_dispatch: true` (config.yaml line 135): review lane is auto-dispatched
  when an implementer calls kanban_request_review.
- `kanban.auto_decompose: true` (line 136): decomposition tasks are auto-created.
- `kanban.failure_limit: 3` (line 139): task reclaims after repeated protocol violations.
- `kanban.max_in_progress_per_profile: 1` (line 138): one in-flight task per profile.
- `sdlc-review` skill is the operational review-handoff guide: three lenses
  (artifact / execution / contract), acceptance-criteria mapping, verification checklist
  before verdict, "Approve only when the acceptance criteria are satisfied and the evidence
  is sufficient."
- `milestone-spec` skill reinforces: "Definition of Done is the acceptance criteria.
  Check each item before declaring done."

---

## What is missing or weak

### 1. No consolidated multi-agent / handoff contract document

The multi-agent workflow guidance is distributed across:

- three profile SOUL.md files,
- the sdlc-review skill,
- config.yaml,

with no single document that states the end-to-end handoff contract: implementer hands off
to reviewer via kanban_request_review with summary + metadata; reviewer uses sdlc-review
lenses; researcher feeds findings to implementer; what each side's "done" evidence must
contain. The vocabulary is consistent, but the contract is implicit.

### 2. Implementer hand-off evidence is under-specified in SOUL.md

Implementer SOUL.md names "Hand off for review" as the final workflow step but does not
define the handoff evidence shape. Researcher and reviewer both reference review handoff
metadata, but there is no implementer-side spec of what must be in it (changed files,
verification commands run, artifacts produced, which acceptance criteria were satisfied,
what remains uncertain).

### 3. Researcher has no explicit cross-profile handoff section

Researcher SOUL.md is detailed on research completion, artifacts, and final verification,
but says nothing about what to pass to an implementer or reviewer when the research is
input to a later implementation/review task. The "Request Follow-Up" section points work
to another profile but does not specify the handoff shape or what evidence the downstream
profile should expect.

### 4. Reviewer SOUL.md is thinner than the skill's expectations imply

The profile doc ends at line 103 (mid "git branch" in the Repository Reality Before Reports
list). There is no explicit "review verdict" section in the SOUL.md itself — the verdict
guidance (approve / request changes / escalate, what the summary must cite) lives in the
sdlc-review skill. The profile doc is therefore shorter than the operational expectations
imposed on the reviewer.

### 5. Completion criteria are task-dependent, not profiled

None of the three profiles define a self-contained, profile-specific "this is what done
looks like" standard beyond the task body. Researcher is the closest (Final Verification
checklist). Implementer and reviewer rely on the task's acceptance criteria plus the
sdlc-review skill for the concrete gate.

### 6. No shared durability-checklist template across profiles

Each profile has its own durability language, but there is no shared checklist or template
that a worker can run through at completion time to confirm the common durability questions
(artifact exists and is verified, claims backed by evidence, scope respected, terminal Kanban
action taken). Researcher has the closest thing; implementer and reviewer do not.

### 7. No explicit statement that review_dispatch is automated

The profile SOUL.md files do not state that review_dispatch is automated (config.yaml
line 135) or how failure_limit behaves. A worker reading only the profile SOUL.md would not
see that the review lane is auto-dispatched or that three protocol violations trigger
reclaim. This is operational knowledge that currently lives only in config.

---

## Observed behavior in this task's history (confirms the infrastructure is live)

- This task (t_a1c50f71) has had 8 prior runs that exited cleanly (rc=0) without calling
  kanban_complete or kanban_block — each counted as a protocol violation.
- After 3 violations the dispatcher gave up and re-queued as ready; this is the 9th run
  (run_id 28), and the task was promoted back to running after the failure_limit handling.
- The failure_limit: 3 and max_in_progress_per_profile: 1 settings are actively enforced.
- The repeated silent-exit pattern confirms that the terminal-kanban-action requirement is
  real and enforced, but also that a worker can fail it repeatedly without an explicit
  in-profile reminder of the requirement — the enforcement is operational, not instructional.

---

## Summary

- **Durable findings / artifacts:** well covered by Researcher; weakly covered by
  Implementer (named but not specified); implicitly required of Reviewer via the sdlc-review
  skill but not stated in the Reviewer SOUL.md itself.
- **Review handoff evidence:** referenced by Researcher and Reviewer; not defined by
  Implementer; operationalized by sdlc-review skill; no consolidated contract document.
- **Completion criteria:** task-body acceptance criteria are the system of record, reinforced
  by milestone-spec skill ("Definition of Done is the acceptance criteria"). Researcher has
  the most explicit self-check; Implementer and Reviewer rely on the task + skill.

---

*No files were modified during this inspection. This artifact is the only durable output.*
