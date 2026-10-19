# Status and retrospective (2026-10-18)

## Update 2026-10-19: first real test
Four knowledge-sharing transcripts: facts verified but useless to a reader ("Person X said …"), pages read as lists.
Diagnosis in [INGEST-ANALYSIS.md](INGEST-ANALYSIS.md); decision [ADR-0018](decisions/ADR-0018-the-model-writes-the-wiki.md):
**the model now writes the wiki** (agent session per source, sandboxed; `kb ingest`, `kb ask`, `kb lint`). Added: stop/rollback/remove
(`kb rollback`, `kb remove`, Cancel in `kb serve`); fixed: topic data was never committed.

Update: v1 removed; one assistant over wiki, code repositories (`code_repos` with descriptions), Jira tools and
screenshots (`kb ask --image`, `kb code-ask`, `kb chat`, Discuss in `kb serve`). Architecture: [architecture.html](architecture.html).

## Where we are
The mini-flow runs **end to end on a standard work laptop** (Windows 11, no admin rights, Windows PowerShell 5.1,
GPT-6 Luna via GitHub Copilot). On the fictional sample corpus: 4 sources → 19 verified facts, 0 rejected,
**38/38 citations verified**, the planted discrepancy found, answers cited to page / minute / Jira comment.
About 25 model calls and 130k tokens for 4 small sources; an answer takes about 5 s.

Next: the first real Orders documents ([REAL-DATA-TEST.md](REAL-DATA-TEST.md)).

## Done
| Milestone | Delivered |
|---|---|
| M0 Foundation | blueprint repo (private), plugin registry, JSON schemas, config, scripted commits, pre-commit guard (secrets, schemas), ADR-0001…0017, PRODUCT.md |
| M1 Setup | `doctor.cmd` (read-only machine check), `setup.cmd` (Python per user or embeddable, packages, Git, hooks, Copilot runtime, self-test), verified on the work laptop |
| S1 Model from scripts | Copilot SDK and CLI adapters, both verified on Windows; `kb model list/set` (GPT-6 Luna) |
| M2 Collect and extract | inbox, files, Git repository at a ref, Jira (JQL); PDF (pages, tables, figures), DOCX, HTML, e-mail, VTT/SRT, Jira JSON, code, text |
| M3 Catalog and search | one source = one commit, dedup by SHA-256, large originals in `store/`, SQLite FTS5 search, glossary by rules |
| M4 Gateway and meter | routing per task, one-model override, token meter per call, budget limit |
| M5 LLM Wiki | ingest (verified facts with quotes, summaries, topic pages, discrepancies, index/log/hot), `ask` with citations, `code-ask` with `path:line@commit`, `verify` |
| M6 Publish and use | dashboard (offline single file, optional branding), `kb serve` (chat-style discussions with a sidebar, add files with a step tracker, wiki shown inside the app), Copilot CLI instructions and 6 skills |
| Pitch | 8-slide deck with real prototype output |

## Modules
**Implemented:** `core` (config, registry, schemas, gitops, secrets, pre-commit) · `llm` (gateway, meter, SDK/CLI/fake
adapters, smoke) · `connectors` (folder inbox, git repo, Jira) · `extractors` (PDF, DOCX, HTML, e-mail, transcripts,
Jira JSON, code, text) · `knowledge` (catalog, search, ingest, pages, glossary, ask, code, verify) · `publish`
(dashboard, local web app) · setup (doctor, setup, kb.cmd) · Copilot integration (AGENTS.md, skills) · tests (29).

**Not implemented yet:**
| Module / feature | Planned in | Notes |
|---|---|---|
| OCR for scanned PDFs | M2 | scans are detected (`needs_ocr`) but not read |
| Excel (.xlsx), Outlook (.msg), Confluence | M2 / D17 | file kinds known, no extractor |
| Microsoft Graph (Outlook, OneDrive, Teams) | D17 | needs IT approval; later |
| Local transcription (Whisper) | D14 | optional personal module |
| Figures in answers ("where do I click?") | D16 | figures are extracted, not yet captioned or used in answers |
| Lint (contradictions over time, stale pages, orphans) | M5 | only citation `verify` exists |
| Decision log (ADR page type), corrections workflow | D20, trust slide | |
| Review workflow (draft → reviewed) | ADR-0005 | all pages stay `draft` |
| Gold-set evaluation script (30 questions) | PRODUCT.md B1 | template only |
| Figures read by the model, OCR for scans | ADR-0018 | figures are offered to the model; scans still unread |
| Semantic search (embeddings) | D19 | only if FTS5 measurably misses |

## Architecture assumptions deferred
- **Authority hierarchy and validity dates (D8, D9, ADR-0006):** fields exist, nothing sets or uses them; discrepancies
  are flagged but not ranked by authority or date. No diff/review list when a new version of a source arrives.
- **Single-writer queue / ingest as a service (D10, ADR-0007):** `queue/` and its schema exist; `kb serve` uses an
  in-process lock instead. No submission workflow for other users yet.
- **Audience and scope, core vs client (D12, D13, ADR-0015):** fields only, no logic.
- **Build vs adopt (ADR-0017):** still "proposed"; no review of existing LLM Wiki implementations done.
- **Spikes S3 (PDF benchmark), S4 (FTS5 on 15 questions), S5 (weak model on real sources):** not run; S5 starts with
  the real-data test.
- **Cache and retry decorators on the gateway:** retry exists only for invalid JSON; no response cache.
- **Blueprint versioning (semver, UPGRADE.md), Windows CI:** not started.

## What went well
- **Provenance holds:** every published fact has a verbatim quote checked by code; tests prove that invented quotes
  and tampered pages are caught. 100% citation checks on both machines.
- **The biggest unknown was settled early:** spike S1 proved that scripts can call the model, so the weak model is
  used for small, strictly typed tasks rather than open-ended chat.
- **Weak model, good results:** with strict JSON schemas and deterministic checks, GPT-6 Luna produced 0 rejected
  facts on the samples and found the discrepancy.
- **Fast feedback from the real laptop:** doctor, setup and smoke reports made each Windows problem visible and
  fixable within minutes.
- **A scripted model in tests** makes the whole flow testable offline in ~10 s.
- **No company data in the blueprint:** fictional samples, branding read from the instance only.

## What went badly
- **Windows PowerShell 5.1 traps cost four setup rounds:** stderr turned into fatal errors under `Stop`; double quotes
  stripped from native arguments; `PSModulePath` inherited from PowerShell 7; `$PSScriptRoot` empty in `param()`.
  The Windows parts were only linted on macOS, never run.
- **Assumptions about tools were wrong:** the SDK runtime has no `login`; the npm `copilot.CMD` shim cannot be started
  by name; the CLI usage file repeats tokens three times; a reasoning event was taken as the answer.
- **Encoding:** tests read files with the Windows default (cp1252).
- **Prompt quality first time:** the conflict check missed the planted discrepancy until the prompt was made explicit.
- **Commit granularity:** the mini-flow landed as one large commit.
- **Self-test takes ~3.5 min on Windows** (vs 10 s on macOS), probably antivirus scanning many small Git commits.

## Points for improvement
1. **Windows CI** (GitHub Actions `windows-latest` has Windows PowerShell 5.1): run setup and tests on every push;
   it would have caught most of the setup failures.
2. **Meter premium requests**, not only tokens, and show them per document; add a confirm step before large ingests.
3. **Fewer calls per document:** merge topic synopsis and conflict check; larger windows when the model allows it.
4. **Gold-set evaluation script** with the Orders team's 30 questions: accuracy, citation correctness, time, cost.
5. **OCR fallback** for scans and **figure captions** for "where do I click?".
6. **Use authority and validity dates** in discrepancies (which source wins, and since when).
7. **Review workflow:** mark pages reviewed, file corrections from the dashboard / app.
8. **Lint:** stale pages, orphans, contradictions across versions.
9. **Test the Copilot skills** in the real Copilot CLI and adjust wording.
10. **Smaller, atomic commits** for features, as the knowledge base already does for data.
