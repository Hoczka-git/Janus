# Obsidian Vault Versioning Decision Document

**Vault path:** `/mnt/c/Users/dan11/Documents/HermesVault`
**Decision date:** 2026-09-01
**Based on:** Vault audit (t_1138b7e6) + direct file inspection

---

## Executive Summary

The HermesVault is a **minimal, low-risk vault** with no credentials, tokens, or secrets.
It contains 16 fitness notes (~40 KB) and a co-located portable Obsidian Electron app (~374 MB).
The app binary is the only thing that must be excluded from version control.
All notes are safe to version. No files must be blocked from a private repo.

---

## 1. File Classification

### Category 1 — Safe to version (notes + useful config)

| Path | Type | Size | Notes |
|------|------|------|-------|
| `Obsidian/02 - Areas/Fitness/*.md` (16 files) | Markdown notes | ~40 KB total | Fitness notes: strength, running, body composition, goals, benchmarks. Plain text, no secrets. |
| `.obsidian/app.json` | Config | 2 B | Empty/default. Safe. |
| `.obsidian/appearance.json` | Config | 2 B | Empty/default. Safe. |
| `.obsidian/core-plugins.json` | Config | 696 B | Plugin enable/disable state. Useful for syncing. |
| `.obsidian/graph.json` | Config | 494 B | Graph view settings. Safe. |

**Rationale:** These are the actual vault content and configuration. Small, text-based, no sensitive data.

### Category 2 — Should be ignored (binaries, session state, trash)

| Path | Type | Size | Reason |
|------|------|------|--------|
| `Obsidian/Obsidian.exe`, `Obsidian.com` | Binary executables | ~248 MB | Portable app — not vault content. |
| `Obsidian/chrome_*.pak`, `*.dll`, `icudtl.dat` | Chromium/Electron binaries | ~47 MB | App runtime. |
| `Obsidian/locales/*.pak` (47 files) | Locale files | ~38 MB | App localization. |
| `Obsidian/resources/app.asar`, `obsidian.asar`, `resources.pak` | Packaged app resources | ~33 MB | App bundle. |
| `Obsidian/resources/app.asar.unpacked/node_modules/*` | Native node modules | small | App dependencies. |
| `Obsidian/snapshot_blob.bin`, `v8_context_snapshot.bin` | V8 snapshots | ~1.1 MB | App runtime. |
| `Obsidian/LICENSE*` | License files | ~20 MB | App licenses. |
| `Obsidian/Uninstall Obsidian.exe`, `vk_swiftshader_icd.json` | Other app files | ~237 KB | App utilities. |
| `.obsidian/workspace.json` | Session state | 6,936 B | Last open files + UI layout. Changes every session — not useful to version. |
| `.trash/` | Trash | empty | Obsidian internal trash. |

**Rationale:** The `Obsidian/` directory is a **portable Electron application** (99.97% of vault size), not vault content. It should never be versioned. `workspace.json` is ephemeral session state.

### Category 3 — Uncertain / context-dependent

| Path | Type | Reason |
|------|------|--------|
| `.obsidian/workspace.json` | Session state | Contains list of last-open files. Not sensitive, but changes constantly. Could be ignored or versioned depending on whether session restore across devices is desired. Currently empty tab + file explorer. |

**Recommendation:** Ignore it. Session state is machine-specific and high-churn.

---

## 2. Sensitive Data Assessment

**No credentials, tokens, passwords, API keys, or secrets were found in any file.**

The only personal data identified:
- `Body Composition.md` — weight range (60.7–70.2 kg), body fat % (12.4–21.4%), FFM. Personal health/fitness data.
- `Athletic Profile.md` — athletic identity, strengths, training history.
- `Goals and Roadmap.md` — strength goals (squat/deadlift/pull-up/dips targets), endurance goals.

**Verdict:** This is personal fitness data, not credentials. It poses no security risk if shared.
Whether to push it to a **public** repo is a personal privacy choice, not a security requirement.
For a **private** repo, it is safe.

---

## 3. Recommended .gitignore

```gitignore
# Portable Obsidian app (374 MB of Electron binaries — not vault content)
Obsidian/

# Session state (ephemeral, machine-specific)
.obsidian/workspace.json

# OS / Obsidian trash
.trash/
.DS_Store
Thumbs.db
```

**What gets versioned with this .gitignore:**
- 16 fitness notes (~40 KB)
- 4 `.obsidian/` config files (~8 KB total)

**What gets excluded:**
- 374 MB portable app
- Session state
- Trash

---

## 4. Files That Must NOT Be Pushed

**None.** No files in this vault contain secrets, credentials, or sensitive data that would pose a security risk.

The only consideration is **personal privacy** (fitness/health data in notes). This is a choice, not a requirement:
- **Private repo:** Safe to push everything (notes + config).
- **Public repo:** Consider whether fitness data (weight, body fat) should be public. The notes are otherwise non-sensitive.

---

## 5. Key Risk: Portable App Co-located with Vault

The `Obsidian/` directory inside the vault is a **full portable Obsidian installation**.
If the vault is synced via Git, Obsidian Sync, or any other tool **without** the `Obsidian/` exclusion:
- 374 MB of binaries would bloat the repo.
- Every app update would generate large diffs.
- Cross-platform sync would pull Windows binaries to macOS/Linux machines.

**This is the single most important finding for any sync/integration strategy.**

---

## 6. Recommendations

1. **Apply the .gitignore above** before any `git init` or sync setup.
2. **Move the portable app out of the vault** (e.g., to `C:\Portable\Obsidian\`) if the vault is to be synced. This avoids accidental inclusion and keeps the vault lean.
3. **Version the notes and `.obsidian/` config** — they are the actual vault content.
4. **Do not version `workspace.json`** — it is ephemeral session state.
5. **No secret scanning is needed** — no credentials exist in the vault.
6. **If using Obsidian Sync or similar**, ensure the sync tool respects the same exclusions (Obsidian Sync syncs the vault root by default and would include the app binaries unless excluded via sync settings).
