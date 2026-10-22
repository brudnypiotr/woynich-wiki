# Design: decisions so far

Status: **M0 implemented** (2026-10-18). Decisions are now maintained as ADRs in [decisions/](decisions/README.md); the table below is the original summary. Changes: D4 → ADR-0004 (Copilot as engine via SDK), D10 → ADR-0007 (simplified queue), PDF → ADR-0009, store → ADR-0010, ids → ADR-0011, commits → ADR-0012.

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
| D17 | **MVP connectors:** inbox folder, Git repo, Jira, exported files; mailbox/OneDrive/Teams via Microsoft Graph **later** (needs IT) | pluggable, see [ARCHITECTURE.md](ARCHITECTURE.md) |
| D18 | **Secrets** in Windows Credential Manager (`keyring`), never in the repo | |
| D19 | **Search:** SQLite FTS5 in MVP; embeddings (RAG) optional later | |
| D20 | **Glossary** is a separate module; **token & cost meter** is a separate feature; **decision records (ADR)** are a page type | see below |
| D16 | **Images are sources:** figures and screenshots extracted from PDFs with page, caption and nearby text | enables "where do I click?" answers |

## Modules
| Module | Purpose | PoC |
|---|---|---|
| `setup/` | bootstrap: Python per-user, venv, packages (proxy/offline), Git check/portable, Copilot CLI check, plain-language report | ✅ |
| `collect/` | inbox folder, Jira (token/export), Confluence/SharePoint export, local repo, `.msg/.eml` files | inbox + Jira + repo |
| `pdf/` | long/complex PDFs: text layer with page markers → table-aware → OCR fallback; per-page quality metrics; figure/screenshot extraction with captions; permissive libraries by default (AGPL optional) | ✅ (no OCR at first) |
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
| `glossary/` | terms and acronyms: definition, synonyms, per-client meaning, source citations; used by transcription correction, search synonyms and pages | ✅ |
| `metering/` | token and cost meter per task / stage / source / model tier; budget limits; cost report on the dashboard | ✅ |
| `decisions/` | decision records (ADR) extracted from Jira, meetings, emails; status and supersession chain | small |
| `search/` | SQLite FTS5 index over text chunks, pages, glossary; query = search first, then read | ✅ |
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
woynich-wiki/
├── setup.cmd, setup/            # bootstrap (no admin)
├── config/                      # profile.yaml (client, authority, sources), models.yaml
├── tools/                       # python modules above
├── skills/                      # tool-neutral task instructions (+ .github/ adapters for Copilot)
├── templates/                   # page and record templates
├── docs/                        # design, architecture, decisions
└── instance/                    # created by `init`: raw/ catalog/ queue/ wiki/ site/  (never committed to the blueprint)
```

## Glossary module
One file per term in `wiki/glossary/` plus an index:
```yaml
term: FDP
expansion: Flight Duty Period
definition: "…" — [[OM-A rev 7]] §7.1
synonyms: [flight duty period, duty period]
scope: core | client:<id>
sources: [...]
```
Built from three inputs: (1) acronym patterns found by scripts ("Flight Duty Period (FDP)"), (2) glossary sections in documents, (3) terms proposed by the model, which are **only suggestions until confirmed**. Used everywhere: transcript correction, search synonyms, linking terms on pages, onboarding.

## Token & cost meter
A decorator on the LLM gateway records every call to `catalog/metering.jsonl`: `task, stage, source_id, model, tier, tokens_in, tokens_out, cost, duration`. Prices per model are kept in `config/models.yaml`. It feeds:
- **budgets** (stop a run when a limit is reached),
- **dashboard** (cost per source, per page, per question).

## Decision records (ADR)
A decision is a first-class page type in `wiki/decisions/`, because "why is it like this?" is the most valuable question.
```yaml
id: DEC-0042
title: Early-start extension of minimum rest
status: proposed | accepted | superseded | rejected
date: 2026-05-03
decided_by: role or forum (e.g. "client workshop", "change board")
context: … — [[Workshop 2026-03-12]] t. 00:42:10
decision: … — [[PROJ-1234]] #c5
consequences: …
supersedes: DEC-0017
superseded_by: null
affects: [[Feature X]], [[Rule Y]]
```
- **How decisions get in:** the classifier flags candidates (Jira status changes and resolutions, comments with "agreed / decided / approved", meeting transcript segments, emails); the model drafts a record **only from cited text**; a human confirms. Nothing becomes `accepted` without a source.
- **How they are used:** feature and configuration pages link to the decisions that shaped them; discrepancy checks compare implementation against the latest accepted decision; the supersession chain answers "what was true on date X".
