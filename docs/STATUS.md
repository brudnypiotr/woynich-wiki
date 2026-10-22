# Status and retrospective (2026-10-18)

## Update 2026-10-19: first real test
Four knowledge-sharing transcripts: facts verified but useless to a reader ("Person X said …"), pages read as lists.
Diagnosis in [INGEST-ANALYSIS.md](INGEST-ANALYSIS.md); decision [ADR-0018](decisions/ADR-0018-the-model-writes-the-wiki.md):
**the model now writes the wiki** (agent session per source, sandboxed; `kb ingest`, `kb ask`, `kb lint`). Added: stop/rollback/remove
(`kb rollback`, `kb remove`, Cancel in `kb serve`); fixed: topic data was never committed.

Update: v1 removed; one assistant over wiki, code repositories (`code_repos` with descriptions), Jira tools and
screenshots (`kb ask --image`, `kb code-ask`, `kb chat`, Discuss in `kb serve`). Architecture: [architecture.html](architecture.html).

Update (ADR-0019): in the Copilot CLI the agent answers from the wiki itself (skills `kb-ask`, `kb-code`; no nested
`kb ask` session, so one premium request per prompt instead of two) and checks its citations with `kb check-answer`.
`kb serve` and `kb chat` keep **one agent session per discussion** (resumed after a restart; told which pages an ingest
changed). Ingest stays in the sandbox. 

## Where we are
The mini-flow runs **end to end on a standard work laptop** (Windows 11, no admin rights, Windows PowerShell 5.1,
GPT-6 Luna via GitHub Copilot). On the fictional sample corpus: 4 sources → 19 verified facts, 0 rejected,
**38/38 citations verified**, the planted discrepancy found, answers cited to page / minute / Jira comment.
About 25 model calls and 130k tokens for 4 small sources; an answer takes about 5 s.

## Done
| Milestone | Delivered |
|---|---|
| M0 Foundation | blueprint repo, plugin registry, JSON schemas, config, scripted commits, pre-commit guard (secrets, schemas), ADR-0001…0017 |
| M1 Setup | `doctor.cmd` (read-only machine check), `setup.cmd` (Python per user or embeddable, packages, Git, hooks, Copilot runtime, self-test), verified on the work laptop; `Wiki.cmd` (desktop shortcut) starts the app, the first start opens a setup (Copilot, model, Jira, repositories); each clone's `kb.cmd` runs its own code |
| S1 Model from scripts | Copilot SDK and CLI adapters, both verified on Windows; `kb model list/set` (GPT-6 Luna) |
| M2 Collect and extract | inbox, files, Git repository at a ref, Jira (JQL); PDF (pages, tables, figures), DOCX, HTML, e-mail, VTT/SRT, Jira JSON, code, text |
| M3 Catalog and search | one source = one commit, dedup by SHA-256, large originals in `store/`, SQLite FTS5 search, glossary by rules |
| M4 Gateway and meter | routing per task, one-model override, token meter per call, budget limit |
| M5 LLM Wiki | ingest (verified facts with quotes, summaries, topic pages, discrepancies, index/log/hot), `ask` with citations, `code-ask` with `path:line@commit`, `verify` |
| M6 Publish and use | dashboard (offline single file, optional branding), `kb serve` (chat-style discussions with a sidebar, add files with a step tracker, wiki shown inside the app), Copilot CLI instructions and 6 skills |

## Modules
**Implemented:** `core` (config, registry, schemas, gitops, secrets, pre-commit) · `llm` (gateway, meter, SDK/CLI/fake
adapters, smoke) · `connectors` (folder inbox, git repo, Jira) · `extractors` (PDF, DOCX, HTML, e-mail, transcripts,
Jira JSON, code, text) · `knowledge` (catalog, search, ingest, pages, glossary, ask, code, verify) · `publish`
(dashboard, local web app) · setup (doctor, setup, kb.cmd) · Copilot integration (AGENTS.md, skills) · tests (29).

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

