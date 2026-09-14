# Knowledge Summary Generation & Obsidian Promotion Pipeline

**Date:** 2026-09-01
**Status:** Design document (no implementation)
**Scope:** Pipeline that consumes `ResearchArtifact` objects and produces curated Obsidian knowledge notes.
**Parent design:** `docs/research_artifact_provenance_design.md` (Source, Finding, ResearchArtifact dataclasses)

---

## 1. Purpose

Define a pipeline that:

1. Takes a structured `ResearchArtifact` (post-capture) and distills it into a durable **knowledge summary**.
2. Routes the summary through a **curation gate** (human review) before promotion.
3. Promotes curated summaries into an **Obsidian vault** as linked, tagged, metadata-rich notes.
4. Handles **incremental updates** when new research arrives for an existing target.

The pipeline operationalizes ADR-002's curation flow (Raw → Operational → Analysis → Curation → Obsidian) for the research domain. It does **not** replace the operational `companies/<TICKER>/knowledge.md` — it produces a separate, curated Obsidian layer.

---

## 2. Pipeline Overview

```text
                          ┌──────────────────────────┐
                          │   ResearchArtifact       │
                          │   (structured dataclass) │
                          └────────────┬─────────────┘
                                       │
                                       ▼
                          ┌──────────────────────────┐
                          │  1. INTAKE & VALIDATE    │
                          │  - schema validation     │
                          │  - provenance checks     │
                          │  - completeness gates    │
                          └────────────┬─────────────┘
                                       │
                                       ▼
                          ┌──────────────────────────┐
                          │  2. SUMMARY GENERATION   │
                          │  - topic grouping        │
                          │  - composite confidence  │
                          │  - entity extraction     │
                          │  - gap identification    │
                          │  → KnowledgeSummary (IR) │
                          └────────────┬─────────────┘
                                       │
                                       ▼
                          ┌──────────────────────────┐
                          │  3. CURATION GATE        │
                          │  - promote / edit / skip │
                          │  - preview rendering     │
                          │  - user decision         │
                          └────────────┬─────────────┘
                                       │
                                       ▼
                          ┌──────────────────────────┐
                          │  4. OBSIDIAN PROMOTION   │
                          │  - frontmatter inject    │
                          │  - wikilink resolution   │
                          │  - write to vault path   │
                          └────────────┬─────────────┘
                                       │
                                       ▼
                          ┌──────────────────────────┐
                          │  5. UPDATE HANDLING      │
                          │  - change detection      │
                          │  - diff & patch          │
                          │  - changelog append      │
                          └──────────────────────────┘
```

The pipeline is deterministic for steps 1, 2, 4, 5. Step 3 is a human decision point (per ADR-002). The pipeline **never** writes to Obsidian without explicit user approval at the curation gate.

---

## 3. Step 1: Intake & Validation

### 3.1 Input

A `ResearchArtifact` instance that has already passed the parent design's `__post_init__` validation (every finding has ≥1 source, confidence is explicit).

### 3.2 Additional Pipeline Validation

| Check | Rule | Failure Action |
|-------|------|----------------|
| Schema | All fields match `ResearchArtifact` schema | Reject with validation error |
| Provenance | Every `Source` has a non-empty `url` | Reject; flag missing URLs |
| Freshness | `accessed_at` timestamps are not in the future | Warn; proceed with flag |
| Completeness | `summary` and `conclusions` are non-empty | Warn; proceed (summary may be generated) |
| Confidence | No finding has confidence `"niski"` without a note | Warn; flag for curation attention |

### 3.3 Output

A validated `ResearchArtifact` ready for summary generation. Warnings are collected and attached to the curation proposal (Step 3) so the user can review data quality issues.

---

## 4. Step 2: Summary Generation

### 4.1 KnowledgeSummary (Intermediate Representation)

The pipeline generates a `KnowledgeSummary` — a structured intermediate representation between the raw `ResearchArtifact` and the final Obsidian note.

```python
@dataclass
class TopicBlock:
    topic: str                              # e.g. "pipeline", "finances"
    findings: list[Finding]                 # original findings (with sources)
    composite_confidence: str               # derived: "niski" | "sredni" | "wyzszy"
    narrative: str                          # 1-3 sentence synthesis of the topic

@dataclass
class KnowledgeSummary:
    target: str                             # research subject (e.g. "GLUE")
    title: str                              # display title
    summary_text: str                       # condensed 2-5 sentence synthesis
    conclusions: str                        # key takeaways
    topic_blocks: list[TopicBlock]          # grouped, ordered findings
    entities: list[str]                     # extracted entity names for wikilinks
    knowledge_gaps: list[str]               # low-confidence or missing areas
    source_count: int                       # total sources across all findings
    high_confidence_count: int              # findings with "wyzszy"
    low_confidence_count: int               # findings with "niski"
    artifact_version: int                   # source artifact version
    generated_at: datetime                  # pipeline run timestamp
```

### 4.2 Topic Grouping

Findings are grouped by their `topic` field. Topics are sorted by:

1. **Composite confidence** (highest first) — well-sourced topics appear first.
2. **Finding count** (most findings first) — within same confidence.
3. **Alphabetical** — stable tiebreaker.

This ordering surfaces the most reliable knowledge first, which matches how a human reviewer scans a research summary.

### 4.3 Composite Confidence Calculation

For each `TopicBlock`, confidence is derived from its constituent findings using a **conservative (weakest-link) rule**:

```
if any finding.confidence == "niski" → composite = "niski"
elif all findings.confidence == "wyzszy" → composite = "wyzszy"
else → composite = "sredni"
```

**Rationale:** A topic is only as strong as its weakest claim. If one pipeline finding is poorly sourced, the entire pipeline topic carries that uncertainty. This prevents high-confidence findings from masking low-confidence ones.

**Alternative strategies** (configurable, not default):
- **Average:** Map niski=1, sredni=2, wyzszy=3; average and round.
- **Majority vote:** Most common confidence among findings.
- **Source-weighted:** Weight by number of sources per finding.

### 4.4 Entity Extraction

Entities are names that should become wikilinks in Obsidian. They are derived from:

1. **Target:** The `ResearchArtifact.target` is always an entity.
2. **Pattern matching** on finding statements:
   - Tickers: `^[A-Z]{3,5}$` (e.g. `GLUE`, `KYMR`)
   - Drug/compound codes: `^[A-Z]{2,}-\d+$` (e.g. `MRT-6160`, `MRT-2359`)
   - Platform names: `**bolded terms**` or `™/®` suffixed names (e.g. `QuEEN™`)
3. **Known entity list:** A static, curated list of entity aliases (e.g. `Roche`, `Novartis`, `Kymera Therapeutics`).

The entity extraction is deterministic and auditable. Each entity links back to the finding(s) that produced it, so the curation gate can show provenance.

**Note:** NER-based extraction (LLM) is explicitly out of scope for the initial pipeline. It can be added as an optional enhancement layer if pattern matching proves insufficient.

### 4.5 Knowledge Gap Identification

Knowledge gaps are areas where the research is incomplete or uncertain. They are identified as:

1. **Low-confidence findings:** Any finding with `confidence == "niski"` generates a gap note: `"Area '{topic}' has low-confidence claim: '{statement}'"`.
2. **Cross-artifact gaps (future):** Topics present in previous artifacts for the same target but absent from the current one. Deferred to a later pipeline version.

Gaps are surfaced in the Obsidian note so the user knows where to focus future research.

### 4.6 Narrative Generation

The `narrative` field for each `TopicBlock` is a 1-3 sentence synthesis of the findings in that topic. Generation strategies:

- **Template-based (default):** Join finding statements with a connector:
  ```
  "Based on {N} sources, {topic} findings: {statement_1}. {statement_2}."
  ```
- **LLM-assisted (optional):** Use a language model to produce fluent narrative from the structured findings. Requires a quality gate (hallucination check) before promotion.

The design favors template-based generation for determinism and auditability. LLM assistance is an optional enhancement that must be flagged in the curation proposal.

---

## 5. Step 3: Curation Gate

Per ADR-002, knowledge promotion is curated — automation assists but does not replace human judgment. The curation gate presents a **promotion proposal** to the user for review.

### 5.1 Promotion Proposal Structure

The proposal contains:

| Field | Source | User can edit? |
|-------|--------|----------------|
| Target | `ResearchArtifact.target` | No (fixed) |
| Title | `ResearchArtifact.title` | Yes |
| Summary text | Generated `summary_text` | Yes |
| Conclusions | Generated `conclusions` | Yes |
| Topic blocks | Generated `TopicBlock`s | Yes (reorder, remove) |
| Entities | Extracted entity list | Yes (add, remove) |
| Obsidian path | Auto-generated from target | Yes |
| Tags | Derived from topics + entities | Yes |
| Warnings | From Step 1 validation | No (informational) |

### 5.2 User Actions

| Action | Effect |
|--------|--------|
| **Promote** | Write the note to Obsidian as-is (or with edits) |
| **Edit & Promote** | Modify fields, then write |
| **Skip** | Do not write; artifact is archived without promotion |
| **Defer** | Save proposal for later review |

### 5.3 Implementation Note

The curation gate is a **human-in-the-loop** interface. In the CLI, this is an interactive prompt or a preview-then-confirm flow. In Telegram/Hermes, it is a message with inline buttons. The pipeline **blocks** until the user decides — it never auto-promotes.

---

## 6. Step 4: Obsidian Promotion

### 6.1 File Format

Promoted notes are standard Obsidian markdown with YAML frontmatter.

**Frontmatter schema:**

```yaml
---
type: knowledge-summary
target: GLUE
version: 1
created: 2026-08-31T14:00:00+00:00
updated: 2026-08-31T14:00:00+00:00
tags:
  - biotech
  - research
  - molecular-glue-degrader
confidence:
  valuation: niski
  pipeline: sredni
  partnerships: wyzszy
source_count: 8
---
```

**Frontmatter fields:**

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"knowledge-summary"` (enables Dataview queries) |
| `target` | string | Research subject (matches `ResearchArtifact.target`) |
| `version` | int | Monotonic counter (starts at 1, increments on update) |
| `created` | datetime | When the Obsidian note was first created |
| `updated` | datetime | When the note was last modified |
| `tags` | list[str] | Obsidian tags (lowercase, hyphenated) |
| `confidence` | map | Per-topic composite confidence (topic → level) |
| `source_count` | int | Total sources cited in the note |

### 6.2 Folder Structure

The Obsidian vault uses a flat-with-type-prefix structure:

```
Obsidian Vault/
└── Knowledge/
    ├── Companies/
    │   ├── GLUE.md
    │   ├── KYMR.md
    │   └── CCCC.md
    ├── Entities/
    │   ├── MRT-6160.md
    │   ├── MRT-2359.md
    │   └── QuEEN.md
    └── Topics/
        ├── Molecular-Glue-Degraders.md
        └── Targeted-Protein-Degradation.md
```

**Rules:**
- **Companies:** One note per `target` (ticker). This is the primary knowledge summary.
- **Entities:** One note per extracted entity (drug, compound, platform). Contains a knowledge card specific to that entity.
- **Topics:** Cross-cutting topic summaries that synthesize multiple company notes.

The pipeline writes to `Companies/` for the primary summary. Entity and Topic notes are generated only when the user explicitly requests them (future scope for automated cross-note synthesis).

### 6.3 Wikilink Resolution

The pipeline converts entity references in finding statements to Obsidian wikilinks:

```markdown
# Before
- MRT-2359 Phase 2 in prostate cancer: 100% PSA response rate

# After
- [[MRT-2359]] Phase 2 in prostate cancer: 100% PSA response rate
```

**Rules:**
- Only entities in the curated entity list are linked.
- First occurrence in the note is linked; subsequent occurrences use bold (`**MRT-2359**`) to avoid link clutter.
- Entity names match Obsidian note titles exactly (case-sensitive).

### 6.4 Source References

Sources are rendered as inline links with access dates:

```markdown
- **Market cap ~$1.88B** (investing.com, 31.08.2026) [confidence: niski]
  - [investing.com GLUE](https://investing.com/equities/monte-rosa-therapeutics) (accessed: 2026-08-31)
```

This preserves the source provenance from the parent design's `Source` objects. Every claim in the Obsidian note traces back to its original source.

### 6.5 Confidence Badges

Each finding in the note carries a confidence badge. The design uses Dataview-compatible inline fields for queryability:

```markdown
- **Roche + Novartis: >$320M upfront, >$7.5B milestones** [confidence:: wyzszy]
```

The `[confidence:: wyzszy]` syntax is a Dataview inline field, enabling queries like:

```dataview
TABLE confidence, sources
FROM "Knowledge/Companies"
WHERE confidence = "niski"
```

### 6.6 Write Mechanism

The pipeline writes to the Obsidian vault via a configured path. Two strategies:

| Strategy | Mechanism | Pros | Cons |
|----------|-----------|------|------|
| **Direct write** (default) | Janus writes to `$OBSIDIAN_VAULT_PATH/Knowledge/Companies/<TARGET>.md` | Simple, deterministic, no agent dependency | Janus must know vault path |
| **Agent dispatch** | Janus produces content → dispatches to Hermes agent → agent writes via obsidian skill | Respects Hermes/Janus boundary | Adds agent latency, non-deterministic |

**Recommendation:** Direct write for the initial implementation. The vault path is a single configuration value (`OBSIDIAN_VAULT_PATH`), consistent with how `markdown_goals.py` uses `GOALS_PATH`. Agent dispatch can be added later if the boundary becomes a concern.

---

## 7. Step 5: Update Handling

When a new `ResearchArtifact` arrives for a target that already has an Obsidian note, the pipeline performs an **incremental update** rather than a full rewrite.

### 7.1 Change Detection

1. Load the existing Obsidian note for `target`.
2. Parse its frontmatter to get `version` and the set of existing finding statements.
3. Generate a new `KnowledgeSummary` from the incoming artifact.
4. **Diff:**
   - **Additions:** Findings in the new summary not present in the existing note.
   - **Confidence changes:** Findings where the composite confidence has changed.
   - **Contradictions:** Findings that directly contradict existing knowledge (same topic, opposing statements).
   - **Removals:** Findings in the existing note not supported by the new artifact (rare; usually kept with a "superseded" flag).

### 7.2 Diff Rendering

The curation gate presents the diff:

```markdown
## Proposed Changes (v1 → v2)

### New findings
- MRT-8102 IND filing completed H1 2026 (confidence: sredni)
- Cash position updated to ~$120M (confidence: sredni)

### Confidence changes
- Partnerships: wyzszy → wyzszy (no change)
- Valuation: niski → sredni (new source added)

### Contradictions
- None detected
```

### 7.3 Patch Strategy

The existing Obsidian note is patched (not rewritten) to preserve any manual edits the user may have made:

1. **New findings** are appended to the relevant `TopicBlock` section.
2. **Confidence changes** update the inline `[confidence:: ...]` field and the frontmatter `confidence` map.
3. **Contradictions** are flagged for user review — the pipeline does not auto-resolve.
4. **Frontmatter** `version` increments; `updated` timestamp refreshes.
5. **Changelog** section is appended (see 7.4).

### 7.4 Changelog Section

Each update appends to a `## Changelog` section at the bottom of the note:

```markdown
## Changelog

- 2026-09-01 (v2): Added MRT-8102 IND filing. Updated cash position.
  - Sources: 2 new findings, 1 confidence upgrade.
- 2026-08-31 (v1): Initial knowledge from research report 2026-08-31.
```

This preserves the knowledge evolution history within the note itself, complementing git history.

### 7.5 Conflict Resolution

When the pipeline detects a contradiction (same topic, conflicting statements):

1. Both claims are shown side-by-side in the curation gate.
2. The user must choose: keep existing, accept new, or keep both with a dispute flag.
3. Disputed claims are marked in the note: `[disputed:: true]` (Dataview queryable).

---

## 8. Examples

### 8.1 Pipeline Walkthrough (GLUE Research Report)

**Input:** `ResearchArtifact` for "Monte Rosa Therapeutics (GLUE) — 2026-08-31" (from parent design, Section 6.2).

**Step 1 — Validate:** Passes schema. Warning: valuation finding has `niski` confidence.

**Step 2 — Generate:**
- Topics: `partnerships` (wyzszy), `pipeline` (sredni), `valuation` (niski), `finances` (sredni).
- Entities: `GLUE`, `MRT-6160`, `MRT-2359`, `MRT-8102`, `QuEEN`, `Roche`, `Novartis`, `Kymera Therapeutics`.
- Gaps: "Valuation has low-confidence claim: 'Market cap ~$1.88B'".

**Step 3 — Curation:** User reviews proposal, edits title, approves promotion.

**Step 4 — Promotion:** Writes to `$OBSIDIAN_VAULT_PATH/Knowledge/Companies/GLUE.md`.

### 8.2 Obsidian Note Output (Abridged)

```markdown
---
type: knowledge-summary
target: GLUE
version: 1
created: 2026-08-31T14:00:00+00:00
updated: 2026-08-31T14:00:00+00:00
tags: [biotech, research, molecular-glue-degrader, mgd]
confidence:
  partnerships: wyzszy
  pipeline: sredni
  valuation: niski
  finances: sredni
source_count: 8
---

# Monte Rosa Therapeutics (GLUE)

## Summary
Clinical-stage biotech with [[MGD]] platform [[QuEEN]]. Roche + Novartis validation with >$320M upfront.

## Conclusions
GLUE is high-risk/high-reward. Key catalysts: [[MRT-6160]] Phase 2, [[MRT-2359]] Phase 2 readout.

## Knowledge

### Partnerships [confidence:: wyzszy]
- **Roche + Novartis: >$320M upfront, >$7.5B milestones** [confidence:: wyzszy]
  - [everyticker GLUE](https://everyticker.com/quote/GLUE) (accessed: 2026-08-31)
  - [Company IR](https://investor.monte-rosa.com/news) (accessed: 2026-08-30)

### Pipeline [confidence:: sredni]
- **[[MRT-6160]]** — VAV1-directed MGD. Phase 1: >90% target degradation. Phase 2 via Novartis. [confidence:: sredni]
- **[[MRT-2359]]** — GSPT1-directed MYC-driven tumors. Phase 2 MODeFIRe-1, 100% PSA response (early). [confidence:: sredni]
- **[[MRT-8102]]** — NEK7-directed MGD. IND filing planned H1 2026. [confidence:: sredni]

### Valuation [confidence:: niski]
- **Market cap ~$1.88B** (investing.com, 31.08.2026) [confidence:: niski]
  - [investing.com GLUE](https://investing.com/equities/monte-rosa-therapeutics) (accessed: 2026-08-31)

### Finances [confidence:: sredni]
- **Cash ~$107M** (Q4 2025) [confidence:: sredni]
  - [everyticker GLUE](https://everyticker.com/quote/GLUE) (accessed: 2026-08-31)

## Related Entities
[[Roche]] | [[Novartis]] | [[Kymera Therapeutics]] | [[MRT-6160]] | [[MRT-2359]] | [[MRT-8102]] | [[QuEEN]]

## Knowledge Gaps
- Valuation: low-confidence claim on market cap (source disagreement: $1.29B–$1.88B).
- Pipeline: Phase 2 readouts not yet available; no clinicaltrials.gov verification.

## Changelog

- 2026-08-31 (v1): Initial knowledge from research report 2026-08-31.
```

### 8.3 Update Scenario

A new report arrives on 2026-09-15 with:
- Updated cash: ~$120M (new 10-Q filing).
- MRT-8102 IND filing confirmed.
- New competitor note: C4 Therapeutics (CCCC) phase 1 data.

**Pipeline detects:**
- **New:** MRT-8102 IND status update, CCCC phase 1 mention.
- **Confidence change:** Finances `sredni` → `wyzszy` (10-Q is primary source).
- **No contradictions.**

**Curation gate shows:**
```
## Proposed Changes (v1 → v2)

### New findings
- MRT-8102 IND filing: CONFIRMED (confidence: wyzszy)
- C4 Therapeutics (CCCC) Phase 1 data released (confidence: sredni)

### Confidence changes
- Finances: sredni → wyzszy (primary source: 10-Q filing)

### Contradictions
- None
```

User approves. Note is patched to `v2`, changelog appended.

---

## 9. Design Decisions & Trade-offs

### 9.1 Why an intermediate representation (KnowledgeSummary)?

The `KnowledgeSummary` decouples the source artifact format from the Obsidian output format. If the artifact model evolves (e.g., adding finding-level versioning), only the summary generation step changes — the Obsidian promotion step is unaffected. Conversely, if the Obsidian format changes (e.g., new frontmatter fields), only the promotion step changes.

### 9.2 Why conservative (weakest-link) composite confidence?

A topic with one well-sourced finding and one poorly-sourced finding is not "medium" quality — it contains a known weak spot. Conservative confidence prevents the Obsidian layer from overstating certainty. Users can always investigate further; they should not be misled by averaged confidence.

### 9.3 Why template-based narrative over LLM synthesis?

- Deterministic: same input → same output.
- Auditable: the pipeline can show exactly how each narrative sentence maps to source findings.
- No hallucination risk: template-based generation cannot invent claims.
- Fast: no LLM latency.

LLM synthesis can be added as an optional "narrative enhancement" step, but it must be gated by a hallucination check and flagged in the curation proposal.

### 9.4 Why direct write over agent dispatch?

The existing Janus pattern (`markdown_goals.py`, `markdown_tasks.py`) writes directly to configured paths. Adding agent dispatch introduces:
- Non-determinism (agent may fail or rewrite).
- Latency (agent round-trip).
- Boundary confusion (Janus producing content, Hermes writing it).

Direct write is simpler and consistent. The vault path is a configuration concern, not an architectural one. If the vault path is on a remote machine, agent dispatch becomes necessary — but that is a deployment detail, not a pipeline design concern.

### 9.5 Why patch updates instead of full rewrite?

Users may manually edit Obsidian notes (add personal commentary, fix formatting, add links). A full rewrite would destroy these edits. Patch-based updates preserve user contributions while incorporating new structured knowledge.

The risk: patches can fail if the note structure has changed significantly. Mitigation: if a patch fails (3 attempts), fall back to presenting the full proposed note in the curation gate for manual merge.

---

## 10. Relationship to Existing Patterns

| Existing Pattern | How This Pipeline Reuses It |
|-----------------|---------------------------|
| `companies/<TICKER>/knowledge.md` | Operational knowledge layer; pipeline reads from it for cross-artifact gap detection |
| `companies/<TICKER>/reports/YYYY-MM-DD.md` | Snapshot storage for `ResearchArtifact` objects |
| `markdown_goals.py` loader | Model for parsing existing Obsidian notes during updates |
| `markdown_goals.py` save/update | Model for writing/patching Obsidian notes |
| `models/` dataclass pattern | `KnowledgeSummary` and `TopicBlock` follow same `@dataclass` pattern |
| `services/attention.py` scoring | Knowledge gaps can be fed to attention engine for research prioritization |
| `services/weekly_review.py` summary | Pattern for periodic "research digest" generation (future) |
| `[source url]` + confidence format | Formalized into source rendering + confidence badges |
| `janus verify-contract` | Schema validation for incoming artifacts (Step 1) |
| ADR-002 curation flow | Curation gate (Step 3) implements the manual curation step |

---

## 11. Out of Scope

- **Automated research collection:** The pipeline consumes artifacts; it does not create them. Artifact creation is the domain of Hermes research skills.
- **Entity graph / knowledge graph:** Linking entities via wikilinks is included; constructing a queryable knowledge graph is not.
- **Cross-note synthesis (auto):** Generating Topic and Entity notes from Company notes is manual in this design. Automated synthesis is a future extension.
- **LLM-based narrative generation:** Optional enhancement only; not in the initial pipeline.
- **Obsidian plugin development:** The pipeline produces standard markdown; no Obsidian plugin API usage.
- **Vector search / embeddings:** Not required for the initial pipeline; wikilinks + tags provide sufficient discoverability.
- **Multi-vault support:** Single vault path only.

---

## 12. Recommended Implementation Sequence

| Phase | Deliverable | Depends On |
|-------|------------|------------|
| 1 | `models/knowledge_summary.py` — `KnowledgeSummary` + `TopicBlock` dataclasses | Parent design (Source, Finding, ResearchArtifact) |
| 2 | `services/knowledge_pipeline.py` — Step 1 (validation) + Step 2 (summary generation) | Phase 1 |
| 3 | `services/obsidian_promoter.py` — Step 4 (promotion) with frontmatter + wikilinks | Phase 1 |
| 4 | CLI: `janus knowledge promote <artifact-path>` — runs Steps 1-3, outputs proposal | Phase 2, 3 |
| 5 | Step 5 (update handling) — diff + patch + changelog | Phase 3 |
| 6 | CLI: `janus knowledge update <target>` — incremental update flow | Phase 5 |
| 7 | Integration with `companies/<TICKER>/` report files as artifact sources | Phase 2 |

Each phase is independently testable. Phase 1-2 are pure domain logic (no I/O). Phase 3+ touch the filesystem.

---

## 13. Files Referenced

- `docs/research_artifact_provenance_design.md` — parent design (Source, Finding, ResearchArtifact)
- `docs/research_knowledge_capture_findings.md` — survey of existing capabilities
- `docs/decisions/002-obsidian-knowledge-layer.md` — ADR-002 alignment
- `docs/vision.md` — system vision (knowledge as a core capability)
- `companies/GLUE/reports/2026-08-31.md` — example research report
- `companies/GLUE/knowledge.md` — example operational knowledge file
- `src/janus/integrations/markdown_goals.py` — markdown load/save pattern
- `src/janus/services/attention.py` — attention scoring (gap prioritization)
