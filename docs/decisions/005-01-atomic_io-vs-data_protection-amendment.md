# ADR-005 Amendment 01: Resolve `atomic_io` vs `data_protection` Layer Overlap

- **Parent:** ADR-005 — Activity Data Ingestion Layer
- **Status:** Accepted
- **Date:** 2026-09-17
- **Decides:** The consolidation strategy for the two overlapping write-protection
  modules discovered after ADR-005 was accepted.

## Context

ADR-005 §4 designated a single choke point for all `data/` writes: the
`atomic_write` / `read_modify_write` primitives in
`src/janus/integrations/atomic_io.py`, wrapped by the new
`src/janus/services/activity_ingest.py` gateway.

However, a second, pre-existing protection module coexists:

- `src/janus/integrations/atomic_io.py` (224 lines) — write-to-temp +
  `os.replace`, single overwrite `.bak` snapshot, inode/mtime/size conflict
  detection, retry with exponential backoff (`read_modify_write_with_retry`).
- `src/janus/integrations/data_protection.py` (847 lines) — write-to-temp +
  `os.replace`, timestamped rotating `.bak`, SHA-256 hash comparison,
  `fcntl.flock` advisory locking, regeneration gating, post-write verification,
  plus a `repair_file` escape hatch and `verify_file_integrity` used by
  `janus data verify`.

At the time of this amendment the live composition is:

| Surface | Routing |
|---|---|
| Model-driven writes (`dispatch_completion` → goals/tasks/milestones/etc.) | → `activity_ingest` → `atomic_io.read_modify_write_with_retry` |
| Legacy CLI-driven full-rewrites (7 modules: `markdown_goals`, `markdown_tasks`, `markdown_followups`, `markdown_inbox`, `workout_md`, `markdown_research`, `services/decisions`, `services/tasks`) | → `data_protection.protected_write` / `protected_append` / `repair_file` |

The two modules therefore do **not** coexist as peers: `data_protection`
already *wraps* a local `atomic_write` primitive (lines 258–296), i.e. the
same write-to-temp + `os.replace` algorithm is implemented twice with
different ancillary policies layered on top. ADR-005's "single choke point"
principle is violated in two ways at once:

1. Two implementations of the atomic-write primitive (duplication).
2. Two entry points for full-rewrite writes on the legacy paths.

This amendment resolves the overlap.

## Decision

We adopt **Option (b): Layered composition.** `atomic_io` becomes the
canonical low-level primitive; `data_protection` becomes the **policy layer**
that wraps `atomic_io` and supplies the safety features the primitive does not
yet carry.

### Why (b) over (a) and (c)

- **(c) Keep two layers with documented coexistence** is rejected outright —
  it contradicts ADR-005 §2's "single choke point must be the ONLY path" and
  leaves the duplication live forever.
- **(a) Deprecate `data_protection`, port everything into `atomic_io`** is the
  "ideal" end state but it is a **code change**, and ADR-005 Amendment 01 is
  the *decision* record that scopes what that migration looks like. The actual
  port is deferred to implementation task
  `t_1f9c2a7` (created as a child of this amendment). Porting now would
  concentrate 5 distinct concerns into one module and would require migrating
  the `janus data verify` / `repair_file` tooling and the `[data_protection]`
  config surface simultaneously — high risk for a docs-first milestone.
- **(b)** is correct *now* because it:
  - Makes the single choke point real **immediately**: `atomic_io.atomic_write`
    is the one implementation of the primitive; `data_protection` must call it
    rather than re-implementing it (enforced by the code change in `t_1f9c2a7`).
  - Lets the higher-assurance policy features (SHA-256 staleness detection,
    flock locking, regeneration gating, post-write verification, rotating
    backups, integrity-verify CLI) remain available on the legacy paths
    **without forcing a simultaneous rewrite of 7 modules**.
  - Preserves a clean dependency direction: `atomic_io` (mechanism) has zero
    dependency on `data_protection` (policy). `data_protection` → `atomic_io`.
    The reverse must never happen.

### Backup strategy

**Timestamped rotating `.bak` (the `data_protection` scheme) is retained for
the policy layer; the simple single-overwrite `.bak` (in `atomic_io`) is used
only when callers opt out of the policy layer.**

Rationale:
- `atomic_io`'s single overwrite `.bak` is sufficient for the
  model-driven gateway path, where `activity_ingest` already deduplicates and
  where a single last-known-good snapshot is adequate for crash recovery
  between `os.replace` and the next successful write.
- `data_protection`'s rotating, time-stamped backups under `.backups/` are
  required for the legacy paths and for `janus data verify` / `repair_file`,
  which need to roll back to a known-good prior version rather than the
  immediately-previous write. Collapsing to single-`.bak` would remove the
  ability to recover from a corruption that was written more than one cycle
  ago.
- The two schemes are reconciled by having `data_protection.backup_previous`
  call `atomic_io.atomic_write`'s directory-creation helper and share the same
  temp-file naming convention; there is no second atomic-replace path.

### Concurrency model

**`fcntl.flock` advisory locking is retained as the policy-layer guard;
detection + retry (inode/mtime/size snapshot) remains in `atomic_io` as the
low-level primitive.**

Rationale:
- `flock` serializes concurrent writers (CLI + Hermes sync) deterministically
  and cheaply for the legacy paths. Dropping it in favor of detect-and-retry
  alone raises the window for write loss under real contention.
- `atomic_io`'s stat-based snapshot is not a lock — it is a *conflict signal*
  that lets the retry layer (`read_modify_write_with_retry`) recover rather
  than silently clobber. Both mechanisms are needed: the lock reduces
  contention to a minimum so retries are rare, and the snapshot catches the
  residual race (two processes both holding the lock across a `read → mutate`
  boundary on different file handles).
- The two compose without contradiction: `protected_write` acquires
  `file_lock`, then calls `atomic_write`; the snapshot check inside
  `read_modify_write` is a no-op on the `protected_write` path because the
  lock already serializes. The gateway path uses `atomic_io` directly and
  relies on the retry layer.

### Features to port into `atomic_io`

Per Option (a)'s spirit — the features that, once `atomic_io` is the sole
primitive, callers need without re-introducing a second write module. The
following are **planned for `t_1f9c2a7`** (not this amendment):

| Feature | Currently in `data_protection` | Port target | Notes |
|---|---|---|---|
| SHA-256 conflict detection | `detect_conflict` / `compute_hash` | `atomic_io` | Replace stat-snapshot with content-hash check (stronger). |
| `fcntl.flock` advisory locking | `file_lock` | `atomic_io` | Optional `lock=True` kwarg; default off to keep primitive zero-dep on `fcntl` for testability. |
| Post-write verification | `post_write_verify` | `atomic_io` | Re-read + compare inside `atomic_write`; opt-out flag. |
| Regeneration gating | `gate_regeneration` | Not ported | Moves to a *policy* concern owned by `activity_ingest`, not the primitive. The `allowed_regenerators` set stays as an `ingest_activities` argument. |
| Rotating backups | `backup_previous` + rotation | `atomic_io` | Opt-in `backup_rotation` kwarg; default stays single `.bak`. |
| `repair_file` / `verify_file_integrity` | top-level functions | CLI tooling | Migrate to a new `src/janus/integrations/data_integrity.py` to keep `atomic_io` focused on writes. |

### Composition after Amendment 01

```text
                       model-driven writes (ADR-005)
   activity_ingest.ingest_activities()
                       │
              read_modify_write_with_retry   ← atomic_io (mechanism)
                       │
              atomic_write  → os.replace
   ```

```text
   legacy CLI-driven full-rewrites
   services.goals / services.tasks /
   markdown_research / markdown_goals /
   workout_md / markdown_followups /
   markdown_inbox / services.decisions
                       │
              protected_write / protected_append  ← data_protection (policy)
                       │
         ┌──────────────┼──────────────┐
   file_lock(flock)     gate_         backup_previous (rotating .bak)
   (serializes)   regeneration       → then → atomic_write ← atomic_io
   (model guard)    (model guard)       (the single primitive)
```

The invariant: **`atomic_io.atomic_write` / `os.replace` is the only place a
`data/` file is replaced.** `data_protection` never calls `os.replace` itself;
it delegates to `atomic_io`.

## Migration Path (for whichever layer is deprecated)

Although Amendment 01 chooses Option (b) (no deprecation today), it records
the migration contract so the eventual port is bounded. Two children tasks are
created:

1. **`t_1f9c2a7` — Make `atomic_io` the sole write primitive.** Migrate
   `data_protection.protected_write` and `protected_append` to delegate their
   `atomic_write`/`backup_previous` calls to `atomic_io`'s implementations
   (de-duplicate the two `atomic_write` bodies), and add the opt-in
   `lock=True` / `verify=True` / `backup_rotation=True` kwargs to
   `atomic_io.atomic_write` per the "Features to port" table. No caller
   behavior changes; both layers expose the same signatures. Blocks on:
   ADR-005 §10 negative "migration surface" — the 5 rewrite call sites.

2. **`t_b2c4d6e` — Fold the policy features into the gateway** (future). Move
   regeneration gating and SHA-256 conflict detection into
   `activity_ingest` / `atomic_io` so the 7 legacy `protected_write` callers
   migrate to `read_modify_write_with_retry` + an `ingest_*` variant. Only
   after this step does `data_protection` become dead code eligible for
   removal under ADR-005's CI grep gate (§6: any `data/` write outside
   `atomic_io` / the integration `read_modify_write` usage is a verification
   failure).

**Deprecation criteria for `data_protection`:** all 18 documented write paths
from `findings/data_inventory_write_paths.md` route through `atomic_io`; the
`[data_protection]` config table is empty/default in `config/config.toml`;
and `janus data verify` / `repair_file` functionality has moved to
`data_integrity.py`. At that point `data_protection.py` is deleted and the
grep gate becomes a hard `git rm`-enforced prohibition.

## Consequences

**Positive**
- The single choke point is real now: `atomic_io` is the only module that
  performs `os.replace`; `data_protection` delegates to it.
- Policy features (regeneration gate, flock, rotating backups, post-write
  verification) remain available on legacy paths with zero behavior change
  to those 7 modules.
- The dependency direction is one-way (`data_protection` → `atomic_io`),
  eliminating the cyclic-risk duplication.
- The migration path is bounded and assignable; no further ambiguity about
  which features move where.

**Neutral**
- Two modules still exist; the naming distinction (`_io` vs `_protection`)
  encodes the mechanism/policy split, which is the intended long-term shape.

**Negative / Risks**
- **Temporary duplication of the write-to-temp algorithm.** Both modules
  still contain an `atomic_write`. This is accepted only until `t_1f9c2a7`
  lands; the grep gate in `src/janus/verification.py` is extended by that task
  to assert that `data_protection.py` does not contain an `os.replace`
  callsite (forcing the delegation).
- **`fcntl` is not available on Windows.** The `file_lock` contextmanager
  already imports `fcntl` lazily (line 417), so the policy layer is
  import-safe on Windows but the lock is a no-op there; `atomic_io`'s
  detect-and-retry remains the cross-platform fallback. Documented, not fixed
  here.
- **Config split.** `[data_ingestion]` configures the gateway's retry/dedup;
  `[data_protection]` configures the policy layer's locks/backups/gating.
  Once the port completes these merge into `[data_ingestion]`. Until then,
  `activity_data_guide.md` §3.2 documents both tables.

## References

- ADR-005 — Activity Data Ingestion Layer (`docs/decisions/005-activity-data-ingestion-layer.md`)
- `src/janus/integrations/atomic_io.py` — the low-level primitive (224 lines).
- `src/janus/integrations/data_protection.py` — the policy layer (847 lines).
- `src/janus/services/activity_ingest.py` — the model-driven gateway (1109 lines).
- `src/janus/services/execution_feedback.py:625` — `dispatch_completion`
  (the Hermes → Janus dispatch entry point, routes through `activity_ingest`).
- `src/janus/verification.py` — the CI grep gate that enforces the single
  choke point (ADR-005 §6).
- `docs/guides/activity_data_guide.md` §3.2 — documents the
  `[data_protection]` config table and the `protected_write` API surface.
