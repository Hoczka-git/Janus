# ADR-002: Obsidian as a Curated Knowledge Layer

## Status

Accepted

## Implementation

Implemented as of 2026-09-23:
- `CurationProposal` model (`src/janus/models/curation_proposal.py`) with
  immutable state transitions (`PENDING` → `APPROVED` → `VAULTED`) and
  TTL-based expiry.
- `obsidian_promoter.py` service (`src/janus/services/obsidian_promoter.py`)
  — Steps 3-5: note rendering (`propose_note_content`), curation dispatcher
  (`curate_proposal`), vault promotion (`promote_to_obsidian`), and audit
  records (`persist_promotion_record`).
- `janus knowledge` CLI surface (`src/janus/knowledge_cli.py`) with
  `promote`, `list`, `approve`, `reject`, and `render` subcommands.
- Vault path resolved from `--vault` flag or `JANUS_OBSIDIAN_VAULT` env var.
- Tests: 114 gate + pipeline tests in `tests/test_curation_gate.py` and
  34 tests in `tests/test_knowledge_pipeline.py`.

The curation gate is the human-in-the-loop checkpoint: a `KnowledgeSummary`
must be explicitly approved (`CurationGateState.APPROVED`) before
`promote_to_obsidian` will write to the vault. Unapproved proposals raise
`CurationGateError`.

---

# Context

The project contains multiple types of information:

- raw data,
- operational artifacts,
- research workspaces,
- reports,
- temporary files,
- structured domain data,
- long-term knowledge.

Automatically placing all of this information into Obsidian would create duplication and noise.

---

# Decision

Obsidian is used as a curated long-term knowledge layer.

It is not the default storage location for all operational artifacts.

The preferred flow is:

```text
Raw Information
       │
       ▼
Operational Storage
       │
       ▼
Analysis
       │
       ▼
Curation
       │
       ▼
Obsidian Knowledge
```

The Curation step is a human decision point: automation proposes, the human
disposes. The pipeline never writes to Obsidian without explicit approval
at the curation gate (see `CurationProposal` state machine in
`src/janus/models/curation_proposal.py`).
