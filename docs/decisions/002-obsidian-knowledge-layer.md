# ADR-002: Obsidian as a Curated Knowledge Layer

## Status

Accepted

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
