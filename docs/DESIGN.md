# Design: decisions so far

Status: **draft**, nothing implemented yet. Pitch: [PITCH.md](PITCH.md). Risks: [CRITICAL-ANALYSIS.md](CRITICAL-ANALYSIS.md).

## Decisions
| # | Decision | Notes |
|---|---|---|
| D1 | **Blueprint repo** (generic, no company data), cloned onto the work laptop; instances are filled there | built on private equipment; instances never leave the company |
| D2 | **Windows only**, no admin rights, user may be non-technical | one-click `setup.cmd` → `setup.ps1` |
| D3 | **Python** for all scripts (local, per-user install from python.org) | PowerShell only for bootstrap |
| D4 | **Agent:** GitHub Copilot (CLI first, VS Code chat as the friendlier option) | instructions written tool-neutral; thin adapters per tool |
| D5 | **Model is configurable** per task in `config/models.yaml`; design assumes a weak model | narrow tasks + deterministic validators |
| D6 | **English** everywhere; quoted sources stay verbatim | |
| D7 | **Provenance rule**: every statement has a source + locator | carried over from the reference project |
| D8 | **Authority hierarchy + freshness** instead of academic tiers | configurable in the profile |
| D9 | **Snapshots + "valid from"**; new source version → diff + review list | |
| D10 | **Read-only wiki, single-writer queue** (ingest as a service) | PoC: folder queue + script |
| D11 | **One instance = one client** (PoC: one functional area) | |
| D12 | **Audience split** (internal / client-shareable): designed, not enabled | future, for a client edition |
| D13 | **Core vs client knowledge** with a promotion workflow | future |
| D14 | **Local transcription (Whisper) is not part of setup**; optional personal module | most laptops have no suitable GPU |

## Modules
| Module | Purpose | PoC |
|---|---|---|
| `setup/` | bootstrap: Python per-user, venv, packages (proxy/offline), Git check/portable, Copilot CLI check, plain-language report | ✅ |
| `collect/` | inbox folder, Jira (token/export), Confluence/SharePoint export, local repo, `.msg/.eml` files | inbox + Jira + repo |
| `pdf/` | long/complex PDFs: text layer with page markers → table-aware → OCR fallback; per-page quality metrics | ✅ (no OCR at first) |
| `transcripts/` | Teams `.vtt/.docx` transcripts → time-stamped text with speakers; glossary correction; optional local Whisper | Teams transcripts |
| `extract/` | DOCX, XLSX, HTML, email, code files → `text.md` with locators | ✅ |
| `classify/` | rules first (path, type, Jira key, metadata), model only for leftovers | ✅ |
| `assess/` | authority level, freshness, status, scope hint | ✅ |
| `catalog/` | one record per source, dedup by hash/id, one commit per source | ✅ |
| `queue/` | submissions (new source, correction), processed serially | ✅ folder |
| `ingest/` | claim extraction, page drafting, discrepancies ⚖️ | small |
| `verify/` | schema, quote ↔ locator, PDF ↔ title, "does source support sentence" | ✅ |
| `site/` | static HTML: catalog, pages, status dashboard | ✅ |
| `query/` | Copilot skill: answer from wiki with citations | ✅ |
| `lint/` | stale pages, missing citations, orphan sources | later |

## Locators per source type
| Type | Locator | Example |
|---|---|---|
| PDF | page (+ section if known) | `p. 47`, `§4.2 p. 47` |
| DOCX / Confluence / HTML | heading path + paragraph | `§ "Rest rules" ¶ 3` |
| Jira | issue + field/comment | `PROJ-1234 description`, `PROJ-1234 #c5` |
| Code | path:line @ commit | `src/Rules/Rest.cs:120@a1b2c3d` |
| Transcript | time stamp (+ speaker) | `t. 00:42:10 (speaker 2)` |
| Email | message-id/date + paragraph | `2026-03-12 "Re: config" ¶ 2` |
| Spreadsheet | sheet + cell/range | `Flows!B12:F20` |

## Repository layout (target)
```
wojnicz/
├── setup.cmd, setup/            # bootstrap (no admin)
├── config/                      # profile.yaml (client, authority, sources), models.yaml
├── tools/                       # python modules above
├── skills/                      # tool-neutral task instructions (+ .github/ adapters for Copilot)
├── templates/                   # page and record templates
├── docs/                        # pitch, design, analysis, user guide
└── instance/                    # created by `init`: raw/ catalog/ queue/ wiki/ site/  (never committed to the blueprint)
```
