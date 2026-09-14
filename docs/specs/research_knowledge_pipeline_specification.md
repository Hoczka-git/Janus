# Research Knowledge Pipeline — Consolidated Specification

**Date:** 2026-09-01
**Status:** Final consolidated specification (no implementation)
**Sources:**
- Survey: `docs/research_knowledge_capture_findings.md` (existing capabilities)
- Design 1: `docs/research_artifact_provenance_design.md` (artifact model + provenance)
- Design 2: `docs/knowledge_summary_obsidian_pipeline_design.md` (summary + promotion pipeline)

---

## 1. Purpose & Scope

Define the end-to-end flow from **raw research output** to **curated Obsidian knowledge** for the Janus system. The pipeline has three layers:

1. **Artifact Model** — structured dataclasses capturing research output, findings, and sources with explicit provenance.
2. **Summary Generation** — deterministic distillation of artifacts into a knowledge summary intermediate representation (IR).
3. **Obsidian Promotion** — human-in-the-loop curation followed by write/patch to the Obsidian vault.

**Non-goals:** Automated research collection, LLM-based narrative generation, entity graph construction, cross-note synthesis, Obsidian plugin development.

---

## 2. Artifact Model

### 2.1 Core Dataclasses

```
ResearchArtifact
├── title, summary, conclusions, artifact_type (report | note | analysis | thesis)
├── target (research subject, e.g. "GLUE")
├── created_at, updated_at, version (monotonic)
└── findings: list[Finding]
    ├── statement, confidence (niski | sredni | wyzszy), topic
    └── sources: list[Source]
        ├── url, title, accessed_at
        └── source_type (web | document | api | dataset | interview)
```

### 2.2 Provenance Rules

| Rule | Requirement |
|------|-------------|
| Every finding | Must have ≥1 Source (zero sources = validation error) |
| Confidence | Set by researcher at capture time; never inferred |
| `accessed_at` | Captures observation time, not publication date |
| Through promotion | Sources and confidence travel with finding to Obsidian |

### 2.3 Versioning

- **Artifact-level:** monotonic `version` field (starts at 1, increments on content change).
- **Finding-level:** no individual versioning; inherits artifact version. Source `accessed_at` acts as per-finding freshness indicator.
- **Persistence:** git-tracked markdown files (existing `companies/<TICKER>/` pattern).

### 2.4 Markdown Serialization

Artifacts serialize to Obsidian-compatible markdown with YAML frontmatter:

```yaml
---
type: report
target: GLUE
version: 1
created: 2026-08-31T14:00:00+00:00
updated: 2026-08-31T14:00:00+00:00
---
```

Body uses structured sections: `## Summary`, `## Conclusions`, `## Findings` with per-topic groupings, confidence tags `[confidence: wyzszy]`, and source links with access dates.

---

## 3. Summary Generation

### 3.1 KnowledgeSummary (Intermediate Representation)

```python
@dataclass
class TopicBlock:
    topic: str
    findings: list[Finding]
    composite_confidence: str       # weakest-link derivation
    narrative: str                  # 1-3 sentence synthesis

@dataclass
class KnowledgeSummary:
    target, title, summary_text, conclusions
    topic_blocks: list[TopicBlock]
    entities: list[str]             # for wikilinks
    knowledge_gaps: list[str]
    source_count, high_confidence_count, low_confidence_count
    artifact_version, generated_at
```

### 3.2 Composite Confidence

**Conservative (weakest-link) rule** — a topic is only as strong as its weakest finding:

```
if any finding.confidence == "niski" → composite = "niski"
elif all findings.confidence == "wyzszy" → composite = "wyzszy"
else → composite = "sredni"
```

Rationale: prevents high-confidence findings from masking low-confidence ones. Configurable alternatives exist (average, majority vote, source-weighted) but conservative is the default.

### 3.3 Topic Ordering & Entity Extraction

**Topic ordering:** by composite confidence (highest first), then finding count (most first), then alphabetical (stable tiebreaker).

**Entity extraction** (deterministic, auditable):
1. Target always becomes an entity.
2. Pattern matching: tickers `^[A-Z]{3,5}$`, drug codes `^[A-Z]{2,}-\d+$`, bolded terms.
3. Static known-entity alias list (Roche, Novartis, etc.).

LLM-based NER is explicitly out of scope.

### 3.4 Narrative Generation

**Template-based (default):** deterministic join of finding statements. No hallucination risk, auditable, fast.

**LLM-assisted (optional):** requires hallucination quality gate and must be flagged in curation proposal.

### 3.5 Knowledge Gap Identification

- Any `niski` confidence finding generates a gap note.
- Cross-artifact gaps (topics present in previous artifacts but absent from current) deferred to future pipeline version.

---

## 4. Obsidian Promotion

### 4.1 Curation Gate (Human-in-the-Loop)

Per ADR-002, automation assists but does not replace human judgment. The pipeline **never** writes to Obsidian without explicit user approval.

**Proposal presented to user:**

| Field | Editable? |
|-------|-----------|
| Target | No (fixed) |
| Title, Summary, Conclusions | Yes |
| Topic blocks | Yes (reorder, remove) |
| Entities | Yes (add, remove) |
| Obsidian path, Tags | Yes |
| Warnings (from validation) | No (informational) |

**User actions:** Promote, Edit & Promote, Skip, Defer.

### 4.2 Vault Structure

```
Obsidian Vault/
└── Knowledge/
    ├── Companies/       (one note per target/ticker)
    ├── Entities/        (one note per drug/compound/platform)
    └── Topics/          (cross-cutting topic syntheses)
```

Pipeline writes primary summary to `Companies/`. Entity/Topic notes generated only on explicit user request (future scope).

### 4.3 Note Format

**Frontmatter:**
```yaml
---
type: knowledge-summary
target: GLUE
version: 1
created: ...
updated: ...
tags: [biotech, research, molecular-glue-degrader]
confidence:
  partnerships: wyzszy
  pipeline: sredni
  valuation: niski
source_count: 8
---
```

**Body:** Summary → Conclusions → Knowledge (per-topic blocks with `[confidence:: wyzszy]` Dataview inline fields) → Related Entities (wikilinks) → Knowledge Gaps → Changelog.

### 4.4 Wikilinks & Source References

- First entity occurrence → wikilink `[[MRT-2359]]`; subsequent → bold `**MRT-2359**`.
- Sources rendered as inline links with access dates.
- Confidence badges use Dataview inline field syntax for queryability.

### 4.5 Write Mechanism

**Direct write** (default): Janus writes to `$OBSIDIAN_VAULT_PATH/Knowledge/Companies/<TARGET>.md`. Consistent with existing `markdown_goals.py` / `markdown_tasks.py` pattern. Agent dispatch deferred as a deployment concern.

### 4.6 Update Handling (Incremental)

When new artifact arrives for existing target:

1. **Load** existing note, parse frontmatter for version + finding statements.
2. **Diff:** additions, confidence changes, contradictions, removals.
3. **Patch** (not rewrite) to preserve manual user edits.
4. **Changelog** section appended with version entry.
5. **Conflict resolution:** contradictions shown to user; pipeline does not auto-resolve. Disputed claims marked `[disputed:: true]`.

Fallback: if patch fails (3 attempts), present full proposed note in curation gate for manual merge.

---

## 5. End-to-End Pipeline Flow

```
ResearchArtifact (structured dataclass)
    │
    ▼
┌─────────────────────────────┐
│  1. INTAKE & VALIDATE       │  schema + provenance + completeness + freshness checks
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  2. SUMMARY GENERATION      │  topic grouping, composite confidence, entities, gaps, narrative
│  → KnowledgeSummary (IR)    │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  3. CURATION GATE           │  human review: promote / edit / skip / defer
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  4. OBSIDIAN PROMOTION      │  frontmatter, wikilinks, write to vault path
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  5. UPDATE HANDLING         │  diff + patch + changelog (on subsequent artifacts)
└─────────────────────────────┘
```

Steps 1, 2, 4, 5 are deterministic. Step 3 is a human decision point.

---

## 6. Relationship to Existing System

| Existing Pattern | How This Pipeline Reuses It |
|-----------------|---------------------------|
| `companies/<TICKER>/knowledge.md` | Operational knowledge layer; pipeline reads for gap detection |
| `companies/<TICKER>/reports/YYYY-MM-DD.md` | Snapshot storage for `ResearchArtifact` objects |
| `markdown_tasks.py` / `markdown_goals.py` | Loader/saver pattern for markdown + frontmatter |
| `models/` dataclass pattern | `ResearchArtifact`, `Finding`, `Source`, `KnowledgeSummary` follow same `@dataclass` + `__post_init__` validation |
| `services/attention.py` | Knowledge gaps fed as research priority signals |
| `services/weekly_review.py` | Pattern for periodic "research digest" generation |
| `janus verify-contract` | Schema validation for incoming artifacts |
| `[source url]` + confidence format (GLUE files) | Formalized into `Source` model + confidence badges |
| ADR-002 curation flow | Curation gate implements the manual curation step |
| ADR-001 (Janus owns domain state) | Research becomes a first-class Janus domain |

---

## 7. Design Principles

1. **Provenance is non-negotiable.** Every finding traces to its source. No anonymous claims.
2. **Conservative confidence.** Weakest-link composite prevents overstatement of certainty.
3. **Template-first determinism.** Same input → same output. LLM assistance is opt-in and gated.
4. **Human gates the knowledge.** Curation is manual per ADR-002. Automation proposes, human disposes.
5. **Patch, don't rewrite.** Preserves user's manual Obsidian edits across updates.
6. **Markdown as canonical storage.** Human-readable, git-friendly, Obsidian-compatible, no export step.

---

## 8. Recommended Implementation Sequence

| Phase | Deliverable | Depends On | Test Level |
|-------|------------|------------|------------|
| **1** | `models/source.py`, `models/finding.py`, `models/research_artifact.py` | — | Unit (pure dataclasses + validation) |
| **2** | `models/knowledge_summary.py` — `KnowledgeSummary` + `TopicBlock` | Phase 1 | Unit |
| **3** | `services/knowledge_pipeline.py` — Step 1 (validation) + Step 2 (summary generation) | Phase 1, 2 | Unit + integration (deterministic generation) |
| **4** | `services/obsidian_promoter.py` — Step 4 (frontmatter + wikilinks + write) | Phase 2 | Unit + temp-dir integration |
| **5** | CLI: `janus knowledge promote <artifact-path>` — runs Steps 1-3, renders curation proposal | Phase 3, 4 | CLI test |
| **6** | Step 5 (update handling) — diff + patch + changelog | Phase 4 | Unit + integration |
| **7** | CLI: `janus knowledge update <target>` — incremental update flow | Phase 6 | CLI test |
| **8** | Integration with `companies/<TICKER>/` reports as artifact sources | Phase 3 | End-to-end |

Each phase is independently testable. Phases 1-3 are pure domain logic (no I/O). Phases 4+ touch the filesystem.

---

## 9. Minimal Next Steps

1. **Create Phase 1 models** — three dataclasses (`Source`, `Finding`, `ResearchArtifact`) with `__post_init__` validation. This is pure Python with no I/O. Test by constructing the GLUE example from Section 6.2 of the artifact design.
2. **Create Phase 2 models** — `KnowledgeSummary` + `TopicBlock`. Add composite confidence calculation. Test with multi-finding, mixed-confidence fixture.
3. **Build Step 1 + 2 service** — validation + summary generation. Test end-to-end with GLUE artifact fixture, verify deterministic output.

These three steps form a self-contained, fully testable foundation. After Phase 3, the pipeline can generate `KnowledgeSummary` IR from any `ResearchArtifact` — the Obsidian write path can be built and tested independently on top.

---

## 10. Files Referenced

- `docs/research_knowledge_capture_findings.md` — survey of existing capabilities
- `docs/research_artifact_provenance_design.md` — artifact + provenance design
- `docs/knowledge_summary_obsidian_pipeline_design.md` — summary + promotion design
- `docs/decisions/001-hermes-janus-system-model.md` — ADR-001
- `docs/decisions/002-obsidian-knowledge-layer.md` — ADR-002
- `docs/vision.md`, `docs/roadmap.md`, `docs/principles.md`
- `companies/GLUE/reports/2026-08-31.md` — example research report
- `companies/GLUE/knowledge.md` — example operational knowledge
- `src/janus/models/` — dataclass pattern references
- `src/janus/integrations/markdown_tasks.py`, `markdown_goals.py` — markdown load/save patterns
- `src/janus/services/attention.py` — attention scoring (gap prioritization)
