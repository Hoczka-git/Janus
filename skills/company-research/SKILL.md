---
name: company-research
description: "Use when researching a listed company. Saves knowledge to persistent files under /home/dan11hermes/workspaces/companies/<TICKER>/."
---

# Company Research Skill

## Persistent knowledge

For each company use:

```
/home/dan11hermes/workspaces/companies/<TICKER>/knowledge.md
/home/dan11hermes/workspaces/companies/<TICKER>/reports/YYYY-MM-DD.md
```

**Always read existing knowledge before researching.**

- `knowledge.md` is the current state.
- Dated reports are history.

**Create missing directories/files when needed.**

**Never store company knowledge in USER.md or MEMORY.md.**

## Workflow

1. **Check if directory exists:** `/home/dan11hermes/workspaces/companies/<TICKER>/` — if not, create it
2. **Read existing knowledge.md** (if present) before writing new knowledge
3. **Read latest reports** to understand what has already been captured
4. **For new research:** write dated report file `reports/YYYY-MM-DD.md`
5. **Update knowledge.md** with current state — only new/changed facts, source references

## File format

### knowledge.md (current state)

```markdown
# <COMPANY> (<TICKER>, <EXCHANGE>)

**Last updated: YYYY-MM-DD**

## Teza

> Short thesis statement

## Cena i wycena

| Wskaźnik | Wartość | Source |
|---|---|---|
| ... | ... | [url] |

## Kluczowe fakty

- **Fact 1** — [source url]
- **Fact 2** — [source url]

## Katalizatory

| Termin | Zdarzenie | Source |
|---|---|---|
| ... | ... | [url] |

## Confidence

[ brief assessment ]

## Historia raportów

- YYYY-MM-DD: [link to report]
```

### reports/YYYY-MM-DD.md (history)

```markdown
# <COMPANY> (<TICKER>) — Research Report — YYYY-MM-DD

## Cena

| | Wartość | Source |
|---|---|---|
| ... | ... | [url] |

## Wydarzenia

- **Event** — [source url]

## Zmiany vs poprzedni stan

- ...
```

## Source references

Every fact/claim must have a source reference in `[source url]` format.

## When to use

- Before new research: READ existing knowledge.md first
- After research: WRITE report file + UPDATE knowledge.md
- If major changes: UPDATE knowledge.md with revised thesis/confidence
