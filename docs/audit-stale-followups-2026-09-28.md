# Stale Follow-up Audit — 2026-09-28

**Task:** t_2f09b3ab — Remove or rebaseline stale follow-ups
**Auditor:** researcher (run 2201)
**Scope:** Follow-up items linked to ADRs or roadmap items across `docs/decisions/`, `docs/roadmap.md`, `docs/design/`, `docs/specs/`

---

## Result: No stale follow-ups remain. Zero removals, zero rebaselines.

### Audit summary

| Source | Items found | Stale | Action |
|--------|-------------|-------|--------|
| ADR-003 (Canonical Review Topology) | 3 Remaining Uncertainty items | 0 | All resolved or intentionally open |
| ADR-004 (Safe Sync-and-Integrate) | 3 Open Operational Items (§6) | 0 | Operational/runtime notes, still relevant |
| ADR-005 (Activity Data Ingestion) | 2 Remaining Uncertainty + 4 deferred alternatives (§9.1) | 0 | Migration resolved; backup strategy is open design choice; alternatives E-H are recorded design options |
| ADR-005 Amendment 01 | Migration status | 0 | Criteria met 2026-09-22 (PR #204) |
| Consolidated ADR (adr-003-004-005) | 12 follow-up items in disposition table + 2 additional deferred | 0 | All RESOLVED or explicitly DEFERRED; doc states "No stale follow-ups remain" |
| Roadmap (docs/roadmap.md) | Near-term: 22 items; Agency-First: 7 items | 0 | Near-term all [x] except one [~] (curation gate, in progress); Agency-First items are future phased work |
| Design docs (execution_planning, measurement_collection, connection_model, verification_pipeline) | Multiple deferred/future items | 0 | All intentionally deferred with rationale, not stale |

### Why nothing was removed or rebaselined

1. **Prior task t_b84710e6 (PR #261, merged 2026-09-28) already removed/rebaselined 6 outdated ADR follow-up items across 5 docs.** The consolidated ADR disposition table (last updated 2026-09-25) confirms: "No stale follow-ups remain."

2. **Remaining open items are not stale:**
   - ADR-003 §Remaining Uncertainty #3 (review loop limits) — open design question, explicitly not a stale follow-up
   - ADR-005 backup-strategy preference — open design choice, not a correctness defect
   - ADR-005 §9.1 alternatives E-H — recorded design options for future evaluation, not follow-up tasks
   - Roadmap [~] curation gate — in progress, partially implemented
   - Roadmap Agency-First [~]/[ ] items — future phased work per `janus-agency-first-development-phase.md`
   - Design doc deferred items (task dependencies, progress history, contradiction detection, calendar write) — all have explicit deferral rationale

3. **"Last verified" dates are current:** ADR-003/004/005 consolidated = 2026-09-25; roadmap = 2026-09-28; ADR-001/002/003-canonical/vault-versioning/ADR-005 Amendment 01 = 2026-09-24 (all within the last 4 days, verified during recent cleanup passes).

### Conclusion

The follow-up hygiene state is clean. No action required beyond this audit confirmation.

**One-line reason for no changes:** All stale ADR/roadmap follow-ups were already removed or rebaselined by t_b84710e6 (PR #261); remaining items are resolved, intentionally deferred, or current/future work — none are stale.
