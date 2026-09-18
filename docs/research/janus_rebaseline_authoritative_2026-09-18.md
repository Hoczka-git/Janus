# Janus Architecture & Roadmap Re-baseline — Authoritative State
**
Date:** 2026-09-18
**Task:** t_13a8b54a — Re-baseline after completed ADR/reconciliation work
**HEAD:** `2dc1b72` (chore: reconcile stale decisions and update documentation)
**Scope:** Single authoritative list of genuinely open work; stale audit claims removed or explicitly archived.

---

## 1. What Changed Since Prior Reconciliation Reports

| Change | Source | Status |
|--------|--------|--------|
| All 5 previously-flagged uncommitted doc updates committed | `2dc1b72` (commit `c0746b3`) | **RESOLVED — no loss risk** |
| 11 `tmp_*.py` scratch files committed to HEAD | `2dc1b72 --stat` shows all 11 in commit | **Confirmed committed (not untracked)** — see §4 |
| ADR-003/004/005 status fields | Still "Proposed" at HEAD | **CONFIRMED STALE** — `76fd1cd` (Accepted) exists on remote branches but is not on this HEAD |
| All 12 roadmap markers | `[x]` verified in HEAD | **COMPLETE — no gaps** |
| PR #185 merged (test fixes + tmp file removal staging) | `c0746b3` | **Merged to master** |

---

## 2. ADR Status — Current State at HEAD

### ADR-003: Canonical Review Topology (`docs/decisions/003-canonical-review-topology.md`)

| Field | HEAD value | Correct value | Stale? |
|-------|-----------|---------------|--------|
| Status | **Proposed** | Accepted | **YES** |
| Implementation | Fully implemented | Fully implemented | No |
| Claims | Accurate | Accurate | No discrepancies |

**Resolution:** Status field needs backport of `76fd1cd` change. Claims are accurate — Model A (Native Review Lane) is fully implemented and the ADR documents it correctly.

### ADR-004: Safe Sync-and-Integrate Workflow (`docs/decisions/004-safe-sync-integrate-workflow.md`)

| Field | HEAD value | Correct value | Stale? |
|-------|-----------|---------------|--------|
| Status | **Proposed** | Accepted (with implementation caveats) | **YES** |
| Phase 1 (Pre-Implementation Sync) | Implemented | Implemented | No |
| Phase 2 (Implementation) | N/A (worker's job) | N/A | No |
| Phase 3 (Pre-Completion Gate) | **NOT implemented** | Not implemented | **OPEN GAP** |
| Phase 4 (Safe Integration) | **NOT implemented as separate agent** | Superseded — incremental path taken | Documented as superseded, but body text still references it as formal phase |
| Phase 5 (Completion gate) | **NOT implemented** | Not implemented | **OPEN GAP** |

**Resolution:** Status field needs backport of `76fd1cd` change. Body text line 111 still frames `t_36b3d88f` as "the implementation task" — needs front-loaded superseded note.

### ADR-005: Activity Data Ingestion Layer (`docs/decisions/005-activity-data-ingestion-layer.md`)

| Field | HEAD value | Correct value | Stale? |
|-------|-----------|---------------|--------|
| Status | **Proposed** | Accepted (with implementation caveats) | **YES** |
| `atomic_io.py` | Fully implemented | Fully implemented | No |
| `activity_ingest.py` | Fully implemented (1109 lines) | Fully implemented | No |
|| "Sole write gateway" claim (§2/§6) | Substantially accurate — see §3 corrected verdict | Protected write path covers all Janus data files; only outlier is google_calendar.py:42 (token cache) | CLAIM UPDATED — earlier "contradicted" verdict was corrected after codebase inspection |
| CI grep gate for `data/` writes | **NOT implemented** | Not implemented | **OPEN GAP (regression guard)** |

**Resolution:** Status field needs backport of `76fd1cd` change. §2/§6 "sole write gateway" claim is substantially accurate at HEAD — the protected write path (`protected_write()` → `atomic_io.atomic_write`) covers all Janus data files. The only direct-write outlier is `google_calendar.py:42` (OAuth token cache, not data). CI grep gate (GAP-005) remains a valid regression guard.

---

## 3. Claim Audit — Stale/Contradicted Claims in ADR Body Text

### ADR-005 §2/§6: "The single write gateway must be the ONLY path that can modify data/"

**Status:** Partially accurate at HEAD — re-evaluated after codebase inspection.

**Evidence:**
- Service functions (`complete_janus_task`, `update_goal_progress`, `update_milestone_status`) use `protected_write()` (data_protection.py) → `atomic_write(temp+rename)` — NOT direct `write_text()`. This is the actual protected write path for Janus data files.
- `activity_ingest.py` uses `atomic_io.read_modify_write_with_retry()` for RMW operations (808, 877, 988, 1069) — also part of the atomic_io gateway.
- The ONLY direct `write_text()` outside atomic_io / data_protection is `google_calendar.py:42` — an OAuth token cache path, not a Janus data file.
- `protected_write()` itself calls `atomic_write()` (lines 586, 616), so all Janus data mutations flow through the atomic_io primitive.
- Read paths use `.open()` (e.g. `GOALS_PATH.open()`, line 397) — not `read_text()`. The ADR's "read path" framing does not apply.

**Verdict:** The ADR's "sole write gateway" claim is **substantially accurate** at HEAD — the protected write path (`protected_write()` → `atomic_write`) covers all Janus data file mutations. The only direct-write outlier is `google_calendar.py:42` (token cache, not data). The earlier CLAIM audit's "service functions use direct write_text()" finding was **incorrect** — that finding has been removed and replaced with the verified call chain above. CI grep gate (GAP-005) remains a valid regression guard for future accidental direct writes in `data/` paths.

**Action:** Add caveat to §2/§6: "As of HEAD `2dc1b72`, the protected write path (`protected_write()` → `atomic_io.atomic_write`) covers all Janus data files. The only direct-write outlier is `google_calendar.py:42` (OAuth token cache). CI grep gate recommended to catch regressions."

### ADR-004 body text (line 111): "the implementation task (t_36b3d88f; superseded...)"

**Status:** Stale framing. The parenthetical acknowledges superseded status, but the main clause still presents it as "the implementation task."

**Verdict:** Minor — the superseded note is present but buried.

**Action:** Front-load: "the implementation task was t_36b3d88f (superseded — integration completed incrementally through phase-specific tasks t_021f3833, t_4cd8c17f, and others)."

### ADR-004 §10: "Phase 4 requires a separate agent/profile"

**Status:** Partially stale. The document now notes the task is superseded, but the requirement text remains.

**Verdict:** The "separate agent" requirement was never implemented. Integration happened incrementally through other tasks that only delivered Phase 1 (sync primitive).

**Action:** Either remove the requirement or explicitly mark it as superseded with a note that no separate agent was created.

---

## 4. `tmp_*.py` Scratch Files — Corrected Disposition

**Prior report claimed:** 11 untracked scratch files in working tree.
**Actual state at HEAD:** All 11 files are **tracked and committed** in `2dc1b72`.

```
tmp_fix_sw16_rmw.py
tmp_fix_sw16_rule_s3_eq_s2.py
tmp_ingest_sw16.py
tmp_ingest_sw16_v2.py
tmp_ingest_sw16_v3.py
tmp_rw17.py
tmp_rw17_final.py
tmp_rw17_v2.py
tmp_rw17_v3.py
tmp_rw17_v4.py
tmp_sw16.py
```

**Corrected disposition:** These are committed scratch files. They should be removed from the repository (not just the working tree) via a follow-up commit. Removal was staged in PR #185 (merged) but the removal itself is a separate concern from this rebaseline.

---

## 5. Authoritative List of Genuinely Open Work

This is the single source of truth after reconciling all prior reports against HEAD. Items are grouped by category and priority.

### A. ADR Status Fields (mechanical — low effort)

| # | Action | ADR | Effort |
|---|--------|-----|--------|
| A1 | Update status: Proposed → Accepted | ADR-003 | Trivial (1 line) |
| A2 | Update status: Proposed → Accepted (with implementation caveats) | ADR-004 | Trivial (1 line) |
| A3 | Update status: Proposed → Accepted (with implementation caveats) | ADR-005 | Trivial (1 line) |

**Note:** These are mechanical backports of `76fd1cd`. The decision was already made on 2026-09-16; only the HEAD propagation is missing.

### B. ADR Body Text Corrections (documentation accuracy)

| # | Action | ADR | Effort |
|---|--------|-----|--------|
| B1 | Clarify §2/§6 "sole write gateway" claim — protected write path verified; only outlier is google_calendar.py:42 (token cache) | ADR-005 | Low |
| B1a | Confirm §10 "Phase 4 requires separate agent" is superseded — no separate agent was ever created | ADR-004 | Low |
| B2 | Front-load superseded note for t_36b3d88f (line 111) | ADR-004 | Low |
| B3 | Mark "Phase 4 requires separate agent" as superseded or remove | ADR-004 | Low |

### C. Implementation Gaps (genuinely open)

| Priority | Gap | ADR | Effort | Blocker |
|----------|-----|-----|--------|---------|
| **P0** | GAP-004: Phases 3-5 not implemented (pre-completion gate, safe integration, completion gate) | ADR-004 | High | Core correctness — tasks can be marked done without integration verification |
| **P0** | Vault versioning not executed (no `.git` in HermesVault) | Implicit (ADR-002) | Low | Blocks GAP-001, data at risk (16 notes, ~40KB) |
| **P1** | GAP-001: ADR-002 curation gate not implemented (no human approval before Obsidian promotion) | ADR-002 | Medium | Blocks end-to-end knowledge pipeline |
| **P1** | GAP-006: ADR-004 status update — document needs to reflect Phases 3-5 are still open, not completed | ADR-004 | Low | Documentation accuracy |
| **P2** | GAP-003: ADR-003 prompt patch (`prompt_builder.py` Model B language) | ADR-003 | Low | Model B ambiguity in worker prompt (in Hermes repo, not Janus) |
| **P2** | GAP-005: ADR-005 CI grep gate for `data/` write patterns | ADR-005 | Low | Regression protection for write gateway |

### D. Data Layer Follow-ups (user-routed or integrator action)

| # | Item | Source | Disposition |
|---|------|--------|-------------|
| D1 | Route `data/questions.json` to user | Reconciliation report | **URGENT — user decision needed** |
| D2 | Review 3 goals for auto-completion (Maintain regular training, 8-tygodniowa redukcja, Health & Performance) | Reconciliation report | **HIGH — product decision** |
| D3 | Clarify "Zakończenie naprawy workoutów" task (no linked goal, vague scope) | `data/tasks.md` | **HIGH — user clarification** |
| D4 | Process overdue `data/tasks.md` item #3 (due 2026-09-15) | `data/tasks.md` | **HIGH — user/integrator** |
| D5 | Close 6 subsumed endurance challenge tasks | `data/tasks.md` | **MEDIUM — integrator** |
| D6 | Delete 2 stale E2E test follow-ups (`fu-fu-9e53ae7c`, `fu-fu-ba57aff9`) | `data/followups.md` | **MEDIUM — integrator** |
| D7 | Accept or defer vault versioning decision (17+ days stale) | `docs/decisions/vault_versioning_decision.md` | **MEDIUM — user** |

### E. INVESTIGATE Items — Still Open

| Item | Status |
|------|--------|
| Measurement consumers (attention, daily_briefing, weekly_review) unwired | **OPEN** — only `measurement_due` wired in `goal_health.py` |
| Artifact version auto-bump | **OPEN** — `markdown_research.py:update_artifact()` always sets version=1 |
| Goal metric migration (`current_value` legacy field) | **OPEN** — `goals.py:313-328` still reads legacy field |

### F. Deferred (explicitly, no action needed now)

| Item | Reason |
|------|--------|
| Calendar-aware planning | Blocked — requires Google Calendar integration |
| Research knowledge pipeline | Blocked — requires Obsidian vault versioning (D7) |
| Weekly review automation | Vague acceptance criteria |
| Personal finance domain | Low priority |
| Home automation integration | Low priority |
| GitHub Actions billing | External — cannot verify from repo |

---

## 6. Items Removed from Open Work (Resolved)

These were flagged in prior reports as open/risk but are now resolved:

| Item | Prior status | Resolution |
|------|-------------|------------|
| 5 uncommitted doc updates at risk of loss | P0 risk | Committed in `2dc1b72` — no loss risk |
| tmp_*.py untracked scratch files | 11 untracked | **Corrected:** committed in `2dc1b72` (tracked, not untracked) |
| t_36b3d88f stale reference | Unresolved | Marked superseded in `2dc1b72` |
| Roadmap items 113-116 | Open | Marked complete in `2dc1b72` |
| Product backlog: observability schema, goal execution planning | Open | Marked done in `2dc1b72` |
| E2E follow-ups from Sep 12 | Stale | Reconciled in `2dc1b72` |

---

## 7. Consolidated Decision Documents

Two consolidated decision documents exist on remote branches but are **not on HEAD**:

| Document | Created in | Status |
|----------|-----------|--------|
| `docs/decisions/adr-003-004-005-consolidated-decisions.md` (211 lines) | `76fd1cd` | Not on HEAD |
| `docs/decisions/adr-consolidated-decisions.md` (74 lines) | `c74d1ac` | Not on HEAD |

**Recommendation:** Bring `adr-003-004-005-consolidated-decisions.md` to HEAD — it's the clearest statement of record for why ADR-003/004/005 were accepted (reviews from t_985404ff, t_9f249780, t_b41ffe1f all recommend ACCEPT; no ADRs rejected).

---

## 8. Evidence Chain

| Finding | Evidence |
|---------|----------|
| ADR status fields stale at HEAD | `git show 2dc1b72:...` shows "Proposed"; `git show 76fd1cd` shows "Accepted" — 76fd1cd not on HEAD branch |
| 76fd1cd exists on remote branches | `git branch -a --contains 76fd1cd` shows 5 remote branches |
| tmp_*.py committed (not untracked) | `git ls-files tmp_*.py` returns all 11; `git show 2dc1b72 --stat` shows all 11 in commit |
|| Direct `write_text()` outside atomic_io | `google_calendar.py:42` (OAuth token cache, not Janus data); service functions use `protected_write()` → `atomic_write`, RMW uses `read_modify_write_with_retry()` | **CORRECTED §3** — earlier "direct write in service functions" claim was wrong |
| Roadmap markers all complete | Table in reconciliation report §2; all 12 verified at `[x]` |
| Product backlog done items verified | `git show 2dc1b72 -- docs/product_backlog.md` |
| ADR-004 Phase 1 implemented | `src/janus/git_sync.py:267` (`sync_branch`) |
| Phases 3-5 not implemented | `search_files("def integrate|def pre_completion|def safe_complete")` → 0 matches |

---

## 9. Summary

**Total items reconciled:** 60 (from t_3a254c43's reconciliation report)
**Closed/relevant:** 23 (unchanged)
**Open/stale:** 29 → **reduced** — see §5 for the authoritative list
**Deferred:** 6 (unchanged)

**Key corrections from prior reports:**
1. `tmp_*.py` files are committed (not untracked) — disposition is "remove from repo," not "delete from working tree"
2. All three ADR status fields are confirmed stale at HEAD — `76fd1cd` (Accepted) exists on remote branches but was never merged to this HEAD
3. ADR-005 "sole write gateway" claim is substantially accurate — protected write path covers all Janus data files; only outlier is google_calendar.py:42 (token cache)
4. ADR-004 body text still frames t_36b3d88f as "the implementation task" despite superseded note

**Top priority actions:**
1. Route `data/questions.json` to user (URGENT)
2. Backport ADR status field changes from `76fd1cd` (mechanical, low effort)
3. Review 3 goals for auto-completion (HIGH)
4. Address P0 implementation gaps (Phases 3-5, vault versioning)

---

*End of rebaseline document.*
