# Architecture

Goal: a small MVP today that grows by **adding modules, not by rewriting**. New source systems (mailbox, OneDrive, Teams, Confluence), new extractors, new models and new outputs plug in through stable interfaces.

## Principles
1. **One data contract.** Every stage reads and writes the same few records (`SourceRecord`, `ExtractResult`, `Claim`, `Page`), validated by JSON Schema. Stages never share hidden state.
2. **Pipes and filters.** The pipeline is a sequence of independent stages: `collect → extract → classify → assess → ingest → verify → publish`. Each stage is idempotent and can be re-run on its own.
3. **Ports and adapters (hexagonal).** The core knows interfaces (`Connector`, `Extractor`, `LLM`, `SecretStore`, `Publisher`). Jira, Graph, PyMuPDF and Copilot are adapters behind them.
4. **Deterministic first.** Anything a script can decide (type, dedup, authority, locators, validation) is decided by code. The model is a replaceable component with a narrow job.
5. **Single writer.** All changes go through the queue; one worker applies them and commits. Reads are always safe.
6. **Content addressing.** Sources are identified by hash, so re-collecting is free and versions are detected automatically.

## Patterns in use
| Pattern | Where | Why |
|---|---|---|
| **Plugin registry** (entry points + config) | connectors, extractors, publishers | add a new ingestor by dropping a module and one line in `config/plugins.yaml` |
| **Strategy** | extractor chosen by MIME type / extension; PDF tier chosen by page quality | swap or add extraction methods without touching callers |
| **Adapter** | Jira REST, Microsoft Graph, local folder, Git repo → common `SourceRecord` | every system looks the same to the core |
| **Command queue + event log** | `queue/` items (`add_source`, `correction`, `promote`), `log.jsonl` of applied events | no parallel writes; replayable history; "ingest as a service" later is the same queue behind an API |
| **Pipeline / Chain of responsibility** | stage runner with per-stage checkpoints | resume after failure; run one stage for one source |
| **Gateway + Decorator** | `LLM` gateway routes a task to a model tier; decorators add **token and cost metering**, caching, retries, logging | model choice and cost tracking in one place, invisible to callers |
| **Repository** | catalog access (`catalog/records/*.json` today, SQLite later) | storage can change without changing stages |
| **Schema-first DTOs** | JSON Schema for every record + Pydantic models | weak-model output is rejected early, not discovered later |
| **Idempotency keys** | `sha256` of content + source id | safe re-runs, incremental processing |

## Module map
```
core/        contracts (schemas), pipeline runner, queue, event log, config, plugin registry
connectors/  folder_inbox · git_repo · jira · confluence_export · teams_transcripts   (later: graph_mail · onedrive · sharepoint)
extractors/  pdf (text → tables → OCR, images) · docx · xlsx · html · eml/msg · vtt/transcript · code
llm/         gateway, tier routing, metering decorator, prompt templates, output validators
knowledge/   claims · pages · glossary · decisions (ADR) · discrepancies · search index
publish/     static site · status dashboard · exports
skills/      tool-neutral task instructions + Copilot adapters (.github/)
```
A new ingestor = a class implementing `Connector.list()` / `Connector.fetch()` that returns `SourceRecord`s, registered in `config/plugins.yaml`. Nothing else changes.

## Secrets and credentials
- **Never in the repository.** `.env` and any credential file are git-ignored; a pre-commit check scans for token patterns.
- **Default store: Windows Credential Manager** through the Python `keyring` library. It is per-user, uses Windows DPAPI encryption and **needs no admin rights**. Command: `kb secrets set jira` prompts once and stores the token.
- **Fallback:** environment variables (for CI or service accounts), read only at runtime.
- **One `SecretStore` interface** so a company vault (e.g. Azure Key Vault) can replace it later.
- **Least privilege:** read-only tokens and scopes wherever the system allows; each connector declares the scopes it needs.

### Jira
Personal API token or PAT (depending on Jira Cloud or Data Center), stored in Credential Manager. Connector pulls issues by JQL (`project = X AND labels = kb`) with comments and change history.

### Microsoft 365 (Outlook, OneDrive, SharePoint, Teams) via Microsoft Graph
- *Graph Explorer* is Microsoft's web tool to try Graph queries; the connector uses the same API.
- Authentication with **MSAL device-code flow** (a sign-in in the browser, no client secret on the laptop), using **delegated** permissions (`Mail.Read`, `Files.Read`, …) so it can only see what the user can see.
- Needs an **app registration** in the company tenant; whether users may consent themselves or IT must approve depends on tenant policy. That is why it is **not in the MVP**: the design is ready, the connector is added when IT agrees.
- Tokens are cached in Credential Manager, not on disk in plain text.

## Search: SQLite FTS5 now, semantic search later
- **MVP: SQLite FTS5** (built into Python's `sqlite3`, no extra install). It indexes `text.md` chunks by locator, plus wiki pages and the glossary. It is fast, deterministic, works offline and costs no tokens. The query skill **searches first, then reads only the top hits**, which is essential with a weak model and a small context window.
- **Later, optional:** embedding-based retrieval (RAG) as a second `SearchIndex` adapter, merged with FTS results (hybrid). Added only if FTS + glossary synonyms prove insufficient on the test question set.

## Model constraint (current)
The MVP runs on the **one model available today**, which is weak. The architecture assumes this: tiny tasks, strict schemas, validators after every step, search before reading. Because the model sits behind the gateway, a stronger model can later **re-run ingest on the same sources** (the originals and the catalog do not change) and the wiki improves without changing anything else.
