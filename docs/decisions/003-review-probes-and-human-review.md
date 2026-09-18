# ADR-003 Supplement: Delegate-Task Review Probes and Human-in-the-Loop Review

**Status:** Accepted
**Date:** 2026-09-16
**Parent ADR:** `docs/decisions/003-canonical-review-topology.md` (Accepted)
**Resolves remaining uncertainty:** Parallel review fan-out and human-in-the-loop review path (ADR-003 §Remaining Uncertainty #1 and #2)

---

## Context

ADR-003 establishes Model A (Native Review Lane) as the canonical review topology: review is a phase of the *same* task, not a separate child task. ADR-003's "Remaining Uncertainty" section identifies two topics that need separate documentation:

1. **Parallel review fan-out** — how `delegate_task`-based review probes interact with the native review lane, and why this is distinct from Model B's persistent reviewer-child workflow.
2. **Human-in-the-loop review** — what happens when a human manually pulls a `review` task instead of the dispatcher spawning an autonomous reviewer worker.

This document resolves both.

---

## 1. Delegate-Task Review Probes

### 1.1 What review probes are

A **review probe** is a short-lived, same-run parallel subagent spawned via `delegate_task` to investigate *one specific aspect* of the work under review (e.g., "audit this diff for security vulnerabilities", "verify the test plan passes against the reported behavior"). Multiple probes can be spawned in a single `delegate_task` call to run in parallel, each with a narrow, different lens.

Review probes are **read-only investigators**. They do not decide the final verdict on the implementation task. Their output is summarized to the parent agent, which then uses that evidence to inform its own `kanban_request_review` handoff (or, if the parent is the reviewer, its `kanban_complete` / `kanban_request_changes` decision).

### 1.2 How they differ from Model B (Reviewer-Child Workflow)

| Aspect | Review probe (`delegate_task`) | Model B child (`kanban_create`) |
|---|---|---|
| **Lifecycle** | Same process/session as the parent; spawned and reaped within one run. No persistent task record. | Own task card with a unique ID, own body, own run history. Persists across dispatcher ticks. |
|| **Board mutations** | **Blocked.** `delegate_task` children cannot call any kanban lifecycle tool (`kanban_complete`, `kanban_request_changes`, `kanban_block`, `kanban_comment`, `kanban_create`, `kanban_heartbeat`). See `_reject_delegated_child_mutation()` at `tools/kanban_tools.py:85`. | Not applicable — Model B was rejected, but by design it *would* have board mutations. |
| **Verdict authority** | None. The probe returns a summary; the parent acts on it. | Would have had its own verdict authority (this is the path Model B takes and which ADR-003 rejected). |
| **Provenance chain** | The probe is not itself a reviewer on the task card. The formal `review_requested` / `changes_requested` events always record the **parent agent's** identity as the implementer or reviewer. The probe's findings enter the provenance only if the parent cites them in a handoff. | Would have fragmented provenance (own assignee, own events), which is why Model B was rejected. |
| **Concurrency** | Bounded by `delegation.max_concurrent_children` (default: 10) and `delegation.max_spawn_depth` (default: 1, so probe children cannot spawn their own probes). | Bounded by the board's `max_in_progress` setting. |
| **Use case** | Independent verification of a specific property *before* or *alongside* requesting review. | N/A (rejected pattern). |

**Key invariant:** A `delegate_task` review probe **cannot** corrupt the native review lane's provenance chain because it is structurally incapable of writing `review_requested` or `changes_requested` events. The only agent that can transition the implementation task into or out of `review` is the task's own worker (dispatcher-owned, verified via `_is_dispatcher_owned_worker()`) or an orchestrator profile with the kanban toolset.

### 1.3 When to use review probes

Use `delegate_task` probes when:

- **Parallel independent checks are needed** — e.g., one probe audits the security boundary, another runs the integration test suite, a third checks error-handling paths. Give each probe a *different lens* (the `sdlc-review` skill's lens-decorrelation guidance at `sdlc-review/SKILL.md:71` applies here too: vary the inspection rather than duplicating it).
- **The parent agent is the implementer** and wants to gather evidence *before* calling `kanban_request_review`. The probes are not reviewers; they are evidence gatherers.
- **The parent agent is the reviewer** (i.e., the task is in `review` and the reviewer worker was spawned by the dispatcher) and wants to parallelize investigation within the single review run. The reviewer may spawn probes via `delegate_task`, but the **final verdict still comes from the reviewer's own `kanban_complete` or `kanban_request_changes` call** on the task card — not from any probe.

### 1.4 When to use the native review lane instead

Always use `kanban_request_review` for the **formal verdict handoff** that routes the task into the `review` status, regardless of whether probes were used. The native review lane is the only path that:

- Persists the `review_requested` event (with implementer provenance).
- Enables dispatcher budget reservation for the review lane.
- Triggers `changes_requested` notifications to the implementer via `kanban_watchers.py`.
- Preserves reviewer-provenance auto-routing for re-reviews.

Review probes are **complementary** to the native lane, never a replacement for it.

### 1.5 Interaction with the provenance chain

The `sdlc-review` skill's lens-decorrelation note (`sdlc-review/SKILL.md:71`) explicitly endorses using `delegate_task` for parallel ad-hoc review fan-outs. The provenance guarantee holds because:

1. **Event ownership** — only the reviewer worker (the task's own `assignee`) calls `kanban_complete` or `kanban_request_changes`, emitting `changes_requested` with `{reason, implementer, reviewer, status}` (`kanban_db.py:7399-7403`). Probes cannot emit these events.
2. **Reviewer provenance** — `request_review()` reads the latest `changes_requested` event to recover the prior reviewer's profile (`kanban_db.py:7195-7228`). Probe findings are never stored in this field.
3. **No cross-task mutation** — `_enforce_worker_task_ownership` at `tools/kanban_tools.py:183` prevents a worker scoped to task A from mutating task B, and `_reject_delegated_child_mutation` blocks all kanban tools from delegated children entirely.

**Anti-pattern:** Do not spawn a `delegate_task` child and then ask it to call `kanban_request_changes` on the parent task. The call will be refused at the tool wrapper layer with: *"kanban_request_changes refused: delegate_task child agents are not Kanban run owners."* Return findings as a summary to the parent, and let the parent act.

### 1.6 When the reviewer is itself a probe

If a task is dispatched to the `review` lane and the assigned reviewer is an orchestrator that wants to fan out parallel investigation, the reviewer may spawn `delegate_task` probes and then make its own verdict call. In this case:

- The reviewer's `kanban_complete` or `kanban_request_changes` is the only call that transitions the task card.
- The reviewer should cite which probe's findings informed the verdict in the `summary`/`reason`.
- This pattern is **not** Model B. The task identity, event provenance, and run history all remain on the original card — exactly as Model A requires. Model B would have created a *separate* review child card via `kanban_create`; this pattern does not.

---

## 2. Human-in-the-Loop Review Path

### 2.1 What it is

When an implementer calls `kanban_request_review`, the task enters the `review` status. The dispatcher normally auto-claims it and spawns an autonomous reviewer worker with the `sdlc-review` skill force-loaded. However, a **human-in-the-loop review** occurs when a human reviewer pulls a `review` task manually — either through the dashboard UI or by running `hermes kanban` CLI commands — instead of the dispatcher spawning an automated reviewer.

### 2.2 When it happens

| Trigger | Dispatcher behavior | Human behavior |
|---|---|---|
| `kanban.review_dispatch` is `True` (default) | If the task's `assignee` is a real profile, the dispatcher calls `claim_review_task()` (`kanban_db.py:4831`) → `_spawn()` (`kanban_db.py:11045`) force-loads the `sdlc-review` skill (`kanban_db.py:11048-11056`) → spawns a reviewer worker. | N/A — auto-review path. |
| `kanban.review_dispatch` is `False` (human-only board) | The dispatcher **does not enumerate `review_rows`** at all — it guards enumeration behind `review_dispatch_enabled()` (`kanban_db.py:10715`). Review tasks sit in `review` unclaimed until a human pulls them. | Human claims via dashboard or CLI, then acts as reviewer. |
||| `assignee` is not a real profile (e.g., set to a human handle with no profile) | The dispatcher skips the task in the review loop (`skipped_nonspawnable`, `kanban_db.py:11002-11005`), after the `profile_exists` check. | Human pulls and reviews. |
| Human intervenes even when auto-dispatch is enabled | The dispatcher's `claim_review_task` uses a CAS guard (`WHERE status = 'review' AND claim_lock IS NULL`); if the human claims first, the dispatcher's atomic claim returns `None` and it skips the task. | Human claims via CLI/dash, reviewer worker spawn is skipped. |

### 2.3 How a human claims a review task

A human reviewer claims a `review` task through the same `claim_review_task()` function the dispatcher uses (`kanban_db.py:4831`). The function:

1. **Re-checks parent dependencies** — if any parent was reopened to non-`done` while the task waited in `review`, it demotes to `todo` with a `dependency_wait` event (`source_status='review'`) and returns `None`.
2. **Atomically transitions** `review → running` with a CAS guard (`WHERE id = ? AND status = 'review' AND claim_lock IS NULL`).
3. **Creates a new `task_runs` entry** so the human review run is tracked independently from the original worker run (`task_runs.profile` = the task's `assignee`).

The human reviewer's CLI entry point is `hermes kanban` — there is no dedicated `claim-review` subcommand; claiming is handled internally by the dispatcher. A human reviewer using the dashboard or CLI effectively performs the claim + review as one session. The human reviewer then uses the same verdict tools as an autonomous reviewer (see §2.4).

### 2.4 Verdict routing for human reviewers

Once claimed (status = `running`, from `review`), the human reviewer has the **same three verdict options** as an autonomous `sdlc-review` worker, documented in `sdlc-review/SKILL.md`:

| Verdict | Action | Effect |
|---|---|---|
| **Approve** | `kanban_complete` (or CLI: task completes via the normal completion path) | Task transitions `running → done`. Triggers watchers, closes workspace. |
| **Request changes** | `kanban_request_changes(reason=...)` (or CLI: `request-changes <id> <reason>`) | Review run is closed. Task lands in `ready` or `todo` (via `_landing_status_after_parents`). Reassigns to the original implementer recovered from the `review_requested` event payload. Emits `changes_requested` event and wakes the implementer's notifier. |
| **Escalate** | `kanban_block(reason=..., kind=...)` | Task transitions to `blocked` with the given reason. Increments `block_recurrences` (unlike `request_changes` which does not). |

**Important:** `kanban_request_changes` is **not** a block. It does not increment `consecutive_failures` or `block_recurrences` (`request_changes()` in `kanban_db.py:7289` does not touch either counter, mirroring `unblock_task` — see the deliberate preservation comment at `kanban_db.py:7361`). A task can cycle through review indefinitely without tripping block-loop detection. Review-cycle limits are **not yet implemented** in `config_defaults.py` / `kanban_db.py`; the policy design (opt-in warning threshold + hard cap) is specified in `docs/research/review-loop-policy-spec.md` and `docs/research/review-loop-position-statement.md` but remains a future enhancement. Until then, unlimited review cycles are the default and no auto-block is triggered by repeat `changes_requested` events.

### 2.5 Provenance guarantees for human reviewers

The human-in-the-loop path provides the **same** provenance guarantees as the autonomous path:

- **`review_requested` event** — records `{implementer, reviewer}` at handoff time. When the human is the reviewer, `reviewer` is the human's profile/handle (the task's `assignee` at claim time).
- **`changes_requested` event** — records `{reason, implementer, reviewer, status}` on return. For re-reviews, `request_review()` reads the latest `changes_requested` event to recover the original reviewer provenance (`kanban_db.py:7600-7645`), whether that reviewer was an autonomous worker or a human.
- **`sdlc-review` skill** — a human reviewer using the skill gets the same lens-decorrelation guidance (Round 1: Artifact, Round 2: Execution, Round 3+: Contract). The round count is derived from `changes_requested` event history, visible in `kanban_show` output.

### 2.6 Disabling auto-dispatch for human-only boards

Set `kanban.review_dispatch: false` in `config.yaml` (default `True`, defined in `hermes_cli/config_defaults.py:2908`) or via the `HERMES_KANBAN_REVIEW_DISPATCH` environment variable. When disabled:

| The dispatcher's `_dispatch_once_locked` skips enumeration of `review_rows` entirely — enumeration is guarded by `review_dispatch_enabled()` (`kanban_db.py:10676`); when disabled, `review_rows` stays `[]` and no review budget reservation is applied (`kanban_db.py:11118-11135`). |
- No review budget reservation is applied.
- All `review` tasks require a human to manually claim and act.

This is the recommended configuration for boards where human review is the only sanctioned review path (e.g., security-sensitive or compliance-gated work).

---

## 3. Cross-Reference: Verdict Routing Summary

All verdict routing — whether the reviewer is autonomous (spawned by the dispatcher) or human (manual claim) — flows through the `sdlc-review` skill's Quick Reference table:

| Verdict | Tool | Terminal action |
|---|---|---|
| Approve | `kanban_complete` | Implementation phase is done |
| Request changes | `kanban_request_changes` | Returns task to original implementer with reason |
| Escalate | `kanban_block` | Routes to `blocked` for human triage |

The skill is loaded automatically by the review dispatcher for autonomous reviewers (`kanban_db.py:10310-10400` force-loads `sdlc-review` into the reviewer worker's skill set). A human reviewer may load it manually:

```bash
hermes skills load sdlc-review
```

---

## 4. Decision

**Both remaining uncertainties from ADR-003 are resolved as follows:**

1. **Parallel review fan-out** is handled via `delegate_task` review probes (short-lived, same-run, read-only parallelism) for evidence gathering. The **formal verdict** always goes through the native review lane (`kanban_request_review` → `review` → `claim_review_task` → reviewer worker → `kanban_complete`/`kanban_request_changes`). This is structurally distinct from Model B: probes cannot mutate the board, cannot emit review events, and have no persistent task identity. The provenance chain is preserved because only the task's own reviewer worker can call verdict tools.

2. **Human-in-the-loop review** is a first-class path: when a human claims a `review` task (either because `kanban.review_dispatch` is disabled, or because the human claimed it before the dispatcher), the human acts as the reviewer with the full `sdlc-review` skill verdict surface. No separate tool surface is needed — the human uses the same `kanban_complete`, `kanban_request_changes`, and `kanban_block` tools. The dispatcher's CAS guard ensures no double-claim when a human and auto-dispatch race for the same task.

---

## 5. Related Documents

- `docs/decisions/003-canonical-review-topology.md` — Parent ADR (Model A vs Model B decision)
- `skills/devops/sdlc-review/SKILL.md` — Reviewer workflow, lens variation, verdict routing
- `docs/research/findings-review-topology.md` — Research findings on review topology and identified gaps
- `docs/research/review-loop-policy-spec.md` — Review-cycle limits and warning policy
- `docs/research/rejected-review-semantics-synthesis.md` — `request_changes` semantics and parent re-gating
- `docs/research/kanban-request-changes-trace.md` — Full call chain for `request_changes`
