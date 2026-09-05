# Obsidian Vault Audit Report

**Vault path:** `/mnt/c/Users/dan11/Documents/HermesVault` (Windows filesystem, accessed via WSL)
**Audit date:** 2026-09-01
**Total size:** 374 MB
**Total files:** 105 | **Total directories:** 25

---

## 1. Vault Root Structure

```
HermesVault/
├── .obsidian/          # Vault configuration (4 files)
├── .trash/             # Empty trash directory
└── Obsidian/           # Portable Obsidian app (374 MB — 99.97% of vault size)
```

---

## 2. Configuration Files (`.obsidian/`)

| File | Size | Notes |
|------|------|-------|
| `app.json` | 2 B | Empty/default |
| `appearance.json` | 2 B | Empty/default |
| `core-plugins.json` | 696 B | Lists enabled/disabled core plugins |
| `graph.json` | 494 B | Graph view settings (default layout) |
| `workspace.json` | 6,936 B | Last session state (file explorer + empty tab) |

**Enabled core plugins:** file-explorer, global-search, switcher, graph, backlink, canvas, outgoing-link, tag-pane, properties, page-preview, daily-notes, templates, note-composer, command-palette, editor-status, bookmarks, outline, word-count, file-recovery, sync, bases

**Disabled core plugins:** footnotes, slash-command, markdown-importer, zk-prefixer, random-note, slides, audio-recorder, workspaces, publish, webviewer

**Not present:** `plugins/` directory (no community plugins installed), `community-plugins.json`, `themes/`

---

## 3. Notes Content (`Obsidian/`)

### 3.1 Directory Layout (PARA-inspired)

```
Obsidian/
├── 00 - Inbox/          # EMPTY
├── 01 - Projects/       # EMPTY
├── 02 - Areas/
│   ├── Fitness/         # 16 notes (the ONLY populated area)
│   │   ├── Athletic Profile.md (1,249 B)
│   │   ├── Body Composition.md (970 B)
│   │   ├── Dashboard.md (421 B)
│   │   ├── Fitness Benchmarks.md (1,282 B)
│   │   ├── Fitness Dashboard.md (1,357 B)
│   │   ├── Goals and Roadmap.md (1,188 B)
│   │   ├── README.md (761 B)
│   │   ├── Historical Analysis/
│   │   │   ├── Fitness History and Athletic Profile.md (317 B)
│   │   │   └── Training Plans Timeline.md (1,390 B)
│   │   ├── Reviews/
│   │   │   └── Performance Review Template.md (971 B)
│   │   ├── Running/
│   │   │   ├── Running Analysis.md (168 B)
│   │   │   └── Running Progress.md (1,254 B)
│   │   ├── Strength/
│   │   │   ├── Exercise Benchmarks.md (221 B)
│   │   │   ├── Strength Progress.md (1,654 B)
│   │   │   └── Training Analysis.md (257 B)
│   │   └── Workouts/
│   │       └── 2026/
│   │           └── README.md (162 B)
│   └── Investing/
│       └── Companies/   # EMPTY
├── 03 - Resources/      # EMPTY
├── 04 - Reviews/        # EMPTY
└── 99 - Archive/        # EMPTY
```

### 3.2 Notes Summary

- **Total notes:** 16 markdown files
- **Total notes size:** ~40 KB
- **All notes are in:** `02 - Areas/Fitness/`
- **Note sizes range:** 162 B (README.md) to 1,654 B (Strength Progress.md)
- **No attachments** (images, PDFs, etc.) found
- **No tags or frontmatter** inspected (content not read)

---

## 4. Portable Obsidian Application (`Obsidian/`)

The `Obsidian/` directory contains a **full portable Obsidian installation** (Windows Electron app), consuming ~374 MB:

| Category | Files | Size |
|----------|-------|------|
| Main executable | `Obsidian.exe`, `Obsidian.com` | ~248 MB |
| Chromium/Electron binaries | `chrome_*.pak`, `d3dcompiler_47.dll`, `dxcompiler.dll`, `dxil.dll`, `ffmpeg.dll`, `icudtl.dat`, `libEGL.dll`, `libGLESv2.dll`, `vk_swiftshader.dll`, `vulkan-1.dll` | ~47 MB |
| Locales | 47 `.pak` files | ~38 MB |
| Resources | `resources.pak`, `resources/app.asar`, `resources/obsidian.asar` | ~33 MB |
| V8/Electron snapshots | `snapshot_blob.bin`, `v8_context_snapshot.bin` | ~1.1 MB |
| Licenses | `LICENSE.electron.txt`, `LICENSES.chromium.html` | ~20 MB |
| Other | `Uninstall Obsidian.exe`, `vk_swiftshader_icd.json` | ~237 KB |

**This is NOT part of the vault content** — it is the application binary stored alongside the notes. This is unusual and should be noted for any integration work.

---

## 5. Key Observations

1. **Vault is nearly empty.** Only 16 notes exist, all in a single area (Fitness). Most PARA directories (Inbox, Projects, Resources, Reviews, Archive) are empty stubs.

2. **No version control.** No `.git` directory exists. The vault has no history/backup via Git.

3. **No community plugins.** Only core plugins are available; no third-party plugins are installed.

4. **No attachments.** Zero image, PDF, audio, or other non-markdown files exist in the vault.

5. **Portable app co-located.** The Obsidian executable is stored inside the vault directory. This is atypical — normally the app is installed separately. This may affect sync/backup strategies.

6. **Config is minimal.** `app.json` and `appearance.json` are empty (defaults). No custom theme, no CSS snippets, no templates directory.

7. **`.trash/` exists but is empty.** Obsidian's internal trash is not the same as OS recycle bin.

8. **No `templates/` folder** despite the templates core plugin being enabled.

---

## 6. Implications for Integration

- The vault is a **fresh/minimal vault** with limited content — any knowledge-base integration will start from a small corpus.
- The **portable app inside the vault** is a concern: if the vault is synced (Obsidian Sync, Git, etc.), the 374 MB app binary would be included unless excluded.
- **No existing structure** for non-fitness topics — Areas like Investing, Projects, Reviews are stubbed but empty.
- **No community plugins** means no Dataview, Templater, or other automation tools are currently available.
- The vault uses a **PARA-like structure** (00-Inbox, 01-Projects, 02-Areas, 03-Resources, 04-Reviews, 99-Archive) which is a good foundation for expansion.
