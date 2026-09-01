# Structured Research Artifacts & Source Provenance Model

**Date:** 2026-09-01
**Status:** Design document (no implementation)
**Scope:** Janus domain model for research output, knowledge capture, and source provenance.

---

## 1. Purpose

Define a structured, versioned data model for research artifacts that:

- Captures research output as first-class domain objects (not just markdown files).
- Attaches explicit source provenance to every artifact and individual finding.
- Supports confidence tiering per finding.
- Enables deterministic queries (e.g., "show all sources with low confidence").
- Aligns with ADR-002 (Obsidian as curated knowledge layer) and ADR-001 (Janus owns domain state).

This model replaces the current ad-hoc `[source url]` + confidence-text pattern in `companies/GLUE/*.md` with structured dataclasses, while preserving human-readable markdown as the persistence format.

---

## 2. Schema Overview

Three core models form the hierarchy:

```
ResearchArtifact
  ├── title, summary, conclusions, artifact_type
  ├── created_at, updated_at, version
  └── findings: list[Finding]
        ├── statement, confidence, topic
        └── sources: list[Source]
              ├── url, title, accessed_at
              └── source_type
```

---

## 3. Model Definitions

### 3.1 Source

Represents a single cited origin (URL, document, dataset, API).

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Source:
    url: str                              # canonical URL or document URI
    title: str = ""                       # human-readable label
    accessed_at: datetime | None = None   # when the source was captured
    source_type: str = "web"              # web | document | api | dataset | interview
```

**Rationale:** Separating `Source` from `Finding` allows multiple findings to reference the same source without duplication. The `accessed_at` timestamp captures when the information was observed (not when it was published), which is critical for detecting stale data. `source_type` enables filtering by provenance quality (e.g., "show only api-backed findings").

### 3.2 Finding

A single atomic claim or data point, with per-finding confidence and one or more sources.

```python
from dataclasses import dataclass

CONFIDENCE_LEVELS = ("niski", "sredni", "wyzszy")  # low / medium / high

@dataclass
class Finding:
    statement: str                        # the claim or data point
    topic: str = ""                       # category (e.g. "pipeline", "finances")
    confidence: str = "sredni"            # CONFIDENCE_LEVELS
    sources: list[Source] = field(default_factory=list)
```

**Rationale:** Confidence is per-finding (not per-artifact) because different claims within the same report may have different evidentiary strength. This mirrors the GLUE report pattern where price data is "niski" but partnership terms are "wyzsyer". The `topic` field enables grouping and filtering (e.g., "show all pipeline findings across reports").

### 3.3 ResearchArtifact

The top-level container: a structured research output (report, note, analysis).

```python
from dataclasses import dataclass

@dataclass
class ResearchArtifact:
    title: str                            # unique identifier / headline
    artifact_type: str = "report"         # report | note | analysis | thesis
    summary: str = ""                     # 1-3 sentence synthesis
    conclusions: str = ""                 # key takeaways / thesis statement
    findings: list[Finding] = field(default_factory=list)
    created_at: datetime | None = None    # initial capture
    updated_at: datetime | None = None    # last modification
    version: int = 1                      # monotonic version counter
    target: str = ""                      # research subject (e.g. "GLUE", "market")
```

**Rationale:** The `artifact_type` distinguishes between a full research report, a quick note, a deep analysis, or an investment thesis. The `target` field links artifacts to a research subject (ticker, company, domain) without requiring a separate entity model. `version` enables artifact-level versioning (see Section 4).

---

## 4. Versioning Model

Artifacts are versioned at two levels:

### 4.1 Artifact-Level Versioning

- Each `ResearchArtifact` has a monotonic `version` field (starts at 1).
- When content changes (new findings, corrected data), `version` increments by 1.
- `updated_at` is set to the current timestamp.
- Previous versions are preserved as `companies/<TICKER>/reports/YYYY-MM-DD-v<N>.md` or via git history.

**Persistence:** The canonical storage is git-tracked markdown. Each version is either:
- A new dated report file (snapshot model, current GLUE pattern).
- An updated knowledge.md with a changelog entry (living document model).

### 4.2 Finding-Level Implicit Versioning

- Findings are not individually versioned; they inherit the artifact version.
- When a finding's confidence or sources change, the artifact version bumps.
- The `accessed_at` timestamp on each `Source` acts as a per-finding freshness indicator.

**Rationale:** Full finding-level versioning (with UUIDs and history) adds complexity without clear value for the current use case. The artifact-level version + source timestamps provide sufficient auditability. If finding-level history becomes needed later, a `FindingHistory` wrapper can be added without breaking the model.

---

## 5. Provenance Attachment Rules

| Level | Provenance Mechanism |
|-------|---------------------|
| Artifact | `target` field + `created_at`/`updated_at` timestamps + git commit |
| Finding | `confidence` + `sources` list + `topic` |
| Source | `url` + `accessed_at` + `source_type` |

**Rule 1: Every finding must have at least one source.**
A `Finding` with zero sources is a red flag — it represents an unsupported claim. The model should reject this at validation time.

**Rule 2: Confidence is explicit, not inferred.**
Confidence is set by the researcher at capture time, not computed from source count. Three tiers (niski/sredni/wyszy) match the existing GLUE pattern and are sufficient for decision-making.

**Rule 3: Source timestamps capture observation time.**
`accessed_at` is when the agent/researcher observed the data, not the source's publication date. This enables staleness detection (e.g., "this price is 30 days old").

**Rule 4: Provenance is preserved through promotion.**
When a finding is promoted to long-term knowledge (Obsidian), its source list and confidence travel with it. No provenance is lost in the curation pipeline.

---

## 6. Examples

### 6.1 Minimal ResearchArtifact (single finding)

```python
artifact = ResearchArtifact(
    title="GLUE Q3 2026 Cash Position",
    artifact_type="note",
    target="GLUE",
    summary="Cash position updated from latest 10-Q filing.",
    findings=[
        Finding(
            statement="Cash and equivalents: ~$107M (Q4 2025)",
            topic="finances",
            confidence="sredni",
            sources=[
                Source(
                    url="https://example.com/glue-10q",
                    title="GLUE Q4 2025 10-Q Filing",
                    source_type="document",
                    accessed_at=datetime(2026, 8, 31, 14, 30, tzinfo=timezone.utc),
                )
            ],
        )
    ],
    created_at=datetime(2026, 8, 31, 14, 30, tzinfo=timezone.utc),
)
```

### 6.2 Full ResearchArtifact (multiple findings, mixed confidence)

```python
artifact = ResearchArtifact(
    title="Monte Rosa Therapeutics (GLUE) — Research Report — 2026-08-31",
    artifact_type="report",
    target="GLUE",
    summary="Clinical-stage biotech with MGD platform QuEEN. Roche + Novartis validation.",
    conclusions="GLUE is high-risk/high-reward. Key catalysts: MRT-6160 Phase 2, MRT-2359 Phase 2 readout.",
    findings=[
        Finding(
            statement="Market cap ~$1.88B (investing.com, 31.08.2026)",
            topic="valuation",
            confidence="niski",
            sources=[
                Source(url="https://investing.com/equities/monte-rosa-therapeutics",
                       title="investing.com GLUE", source_type="web",
                       accessed_at=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)),
            ],
        ),
        Finding(
            statement="Roche + Novartis partnerships: >$320M upfront, >$7.5B milestones",
            topic="partnerships",
            confidence="wyzszy",
            sources=[
                Source(url="https://everyticker.com/quote/GLUE",
                       title="everyticker GLUE", source_type="web",
                       accessed_at=datetime(2026, 8, 31, 12, 30, tzinfo=timezone.utc)),
                Source(url="https://investor.monte-rosa.com/news",
                       title="Company IR", source_type="document",
                       accessed_at=datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)),
            ],
        ),
        Finding(
            statement="MRT-2359 Phase 2 in prostate cancer: 100% PSA response rate (early)",
            topic="pipeline",
            confidence="sredni",
            sources=[
                Source(url="https://quantisnow.com/ticker/GLUE",
                       title="quantisnow", source_type="web",
                       accessed_at=datetime(2026, 8, 31, 13, 0, tzinfo=timezone.utc)),
            ],
        ),
    ],
    created_at=datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc),
    version=1,
)
```

---

## 7. Persistence Mapping

### 7.1 Markdown Serialization

The structured model maps to a markdown format compatible with the existing `companies/<TICKER>/reports/YYYY-MM-DD.md` pattern and Obsidian frontmatter:

```markdown
---
type: report
target: GLUE
version: 1
created: 2026-08-31T14:00:00+00:00
updated: 2026-08-31T14:00:00+00:00
---

# Monte Rosa Therapeutics (GLUE) — Research Report — 2026-08-31

## Summary
Clinical-stage biotech with MGD platform QuEEN. Roche + Novartis validation.

## Conclusions
GLUE is high-risk/high-reward. Key catalysts: MRT-6160 Phase 2, MRT-2359 Phase 2 readout.

## Findings

### Valuation
- **Market cap ~$1.88B** (investing.com, 31.08.2026) [confidence: niski]
  - [investing.com GLUE](https://investing.com/equities/monte-rosa-therapeutics) (accessed: 2026-08-31)

### Partnerships
- **Roche + Novartis: >$320M upfront, >$7.5B milestones** [confidence: wyzszy]
  - [everyticker GLUE](https://everyticker.com/quote/GLUE) (accessed: 2026-08-31)
  - [Company IR](https://investor.monte-rosa.com/news) (accessed: 2026-08-30)

### Pipeline
- **MRT-2359 Phase 2: 100% PSA response rate (early)** [confidence: sredni]
  - [quantisnow](https://quantisnow.com/ticker/GLUE) (accessed: 2026-08-31)
```

### 7.2 Obsidian Promotion Format

When promoted to Obsidian (per ADR-002), the artifact becomes a note with:

- YAML frontmatter: `type`, `target`, `version`, `created`, `tags`
- Wikilinks to related entities: `[[GLUE]]`, `[[MRT-2359]]`, `[[Roche]]`
- Source references preserved as footnotes or inline links
- Confidence badges: `![confidence::wyzszy]` (Obsidian dataview compatible)

---

## 8. Relationship to Existing Patterns

| Existing Pattern | How This Model Reuses It |
|-----------------|-------------------------|
| `companies/<TICKER>/knowledge.md` | Becomes the living-document view of ResearchArtifact |
| `companies/<TICKER>/reports/YYYY-MM-DD.md` | Becomes the snapshot view (one ResearchArtifact per report) |
| `[source url]` inline citations | Formalized into `Source` objects |
| Confidence tiers (niski/sredni/wyszy) | Preserved as `Finding.confidence` enum |
| `models/` dataclass pattern | New models follow same `@dataclass` + `__post_init__` validation |
| `integrations/markdown_tasks.py` loader | New `markdown_research.py` loader follows same parse/serialize pattern |
| `services/attention.py` scoring | Findings can be scored for freshness/priority |
| `janus verify-contract` pipeline | Research file structure can be validated against schema |

---

## 9. Design Decisions & Trade-offs

### 9.1 Why dataclasses instead of Pydantic?

Janus uses plain `@dataclasses` throughout (`models/task.py`, `models/goal.py`, `models/workout.py`). Adding Pydantic would introduce a new dependency and break consistency. Dataclasses with `__post_init__` validation provide sufficient type safety for this use case.

### 9.2 Why per-finding confidence instead of per-artifact?

The GLUE reports demonstrate that confidence varies within a single report (price data is unreliable, partnership terms are well-sourced). Per-finding confidence is strictly more expressive and enables better filtering.

### 9.3 Why no finding-level versioning?

Finding-level versioning (with UUIDs and history) adds significant complexity. The artifact-level `version` + source `accessed_at` timestamps provide sufficient auditability for the current use case. This can be added later if needed.

### 9.4 Why markdown as canonical storage?

- Human-readable without tooling.
- Git-friendly (diffs, blame, history).
- Obsidian-compatible (no export step needed).
- Matches existing `companies/` pattern.

### 9.5 Why not a separate entity/researcher model?

The current scope is artifact-centric. A separate `Researcher` or `Entity` model (linking all GLUE artifacts) is a reasonable future extension but not required for the initial model.

---

## 10. Out of Scope

- Obsidian write integration (covered by sibling task t_eaa1b2e1).
- Automated research collection (agent skill concern, not domain model).
- Finding-level versioning with full history.
- Entity graph / knowledge graph construction.
- Full-text search or vector embeddings.

---

## 11. Files Referenced

- `companies/GLUE/reports/2026-08-31.md` — existing report pattern
- `companies/GLUE/knowledge.md` — existing knowledge file
- `src/janus/models/task.py` — dataclass pattern reference
- `src/janus/models/goal.py` — dataclass + validation pattern
- `src/janus/models/workout.py` — complex dataclass hierarchy reference
- `src/janus/integrations/markdown_tasks.py` — markdown loader pattern
- `src/janus/integrations/markdown_goals.py` — markdown serialization pattern
- `docs/decisions/002-obsidian-knowledge-layer.md` — ADR-002 alignment
- `docs/research_knowledge_capture_findings.md` — parent task findings
