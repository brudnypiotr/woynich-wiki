# woynich-wiki

`woynich-wiki` (codename) is a **project knowledge base with a paper trail**. It collects project sources (documents, Jira, code, transcripts), keeps the originals, and builds a read-only wiki (the "LLM Wiki" pattern) in which every statement links to its exact source.

This repository is the **blueprint**: generic code, templates and instructions with no project data.

## Quick start on Windows (no admin rights)
1. Clone or unzip the repository into a **short path outside OneDrive**, e.g. `C:\kb\woynich-wiki`.
2. Double-click **`doctor.cmd`**. It is a read-only check of the machine that changes nothing. If it reports blockers, send `doctor-report.json`.
3. Double-click **`setup.cmd`**. It installs a private Python and the packages, finds or unpacks Git, and downloads the Copilot runtime. Safe to run again.
4. In a terminal in the repository folder:
   - `kb login`: sign in to GitHub Copilot once, in the browser
   - `kb llm-smoke`: checks that scripts can use the model; send `instance\reports\llm-smoke.json`
   - `kb init`: creates the knowledge base instance (`instance\`, its own git repository)

## First test: from a PDF to a cited answer (about 5 minutes)
```
kb add samples\sources                 # fictional Example Air sources: OM PDF, meeting, Jira ticket, e-mail
kb ingest                              # the model reads each source and writes the wiki; checks; one commit per source
kb ask "What is the minimum rest before a duty at home base?"
kb site --open                         # dashboard: sources, topics, discrepancies ⚖️, glossary, tokens
```
Expected: pages for the sources and concepts (e.g. minimum rest at home base), an answer citing `p. 3` of the OM and
`t. 00:01:10` of the meeting, and a contradiction (12 h vs 10 h). About one premium request per source and per question.
Then with your own files: `kb add C:\path\to\document.pdf` (or drop files into `instance\inbox\` and run `kb collect inbox`).

### Branding (optional)
Put a logo and a header background into `instance\branding\` (`logo.png` or `logo.svg`, `background.jpg`; a white logo
suits the dark header) and run `kb site`. The dashboard and the `kb serve` sidebar both use them. They are embedded into the single dashboard file; company imagery never goes into this repository.
Set the title in `instance\config\profile.yaml` (`instance: {title: "Orders Rules knowledge base"}`).

### In GitHub Copilot CLI
Start `copilot` in this folder. It reads `AGENTS.md` and offers the skills `/kb-add`, `/kb-ingest`, `/kb-ask`,
`/kb-code`, `/kb-status`, `/kb-verify`. Ask normally ("what is the minimum rest at home base?"): Copilot runs
`kb ask` and repeats the citations. Allow the shell tool for `kb.cmd` when asked.

### Code questions, Jira and screenshots
Describe your local repositories in `instance\config\profile.yaml` (the model may only read them):
```
code_repos:
  - name: inventory-service
    path: C:/Users/you/DEV/inventory-service
    description: Inventory backend (Java). Rules engine, orders; look here for rule logic and parameters.
```
Check with `kb repos`. Then:
- `kb code-ask "How is minimum rest computed?" --evidence` → answer from wiki + code, citing `file:line@commit`;
- `kb ask "What does this screen show?" --image screenshot.png` → the model explains the screen with the wiki;
- `kb chat` → a conversation in the terminal (`/image <file>`, `/save`, `/exit`); in the browser: `kb serve` → a chat
  (paste a screenshot with Ctrl+V, toggle "Code" to include the repositories). **Settings** in `kb serve`: model per
  task tier or one model for all, GitHub Copilot sign-in and quota, keys and tokens (Windows Credential Manager), Jira URL;
- with Jira configured (`jira.base_url` in the profile, `kb secrets set jira-token`) the model can fetch tickets
  (`jira_get`, `jira_search`) during the conversation.

### All commands
`add`, `collect inbox|git|jira`, `ingest`, `ask`, `code-ask`, `chat`, `repos`, `lint`, `remove`, `rollback`, `serve`, `search`, `verify`, `site`, `status`, `model list|set|show`, `secrets set|check`, `login`, `llm-smoke`, `plugins`.

## Documentation
- [docs/architecture.html](docs/architecture.html): architecture (who decides what, workflows, source processing, modules, status) — open in a browser
- [docs/STATUS.md](docs/STATUS.md): what works, what is next, retrospective · [docs/REAL-DATA-TEST.md](docs/REAL-DATA-TEST.md): checklist for the first real documents
- [docs/PITCH.md](docs/PITCH.md): what it is and why (for managers) · [pitch/index.html](pitch/index.html): 8-slide deck
- [docs/PRODUCT.md](docs/PRODUCT.md): personas, baseline, gold questions, success criteria
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): patterns, plugins, secrets, search, connectors
- [docs/decisions/](docs/decisions/README.md): architecture decision records (ADR)
- [docs/DESIGN.md](docs/DESIGN.md), [docs/VISION.md](docs/VISION.md), [docs/CRITICAL-ANALYSIS.md](docs/CRITICAL-ANALYSIS.md)

## Development (macOS / Linux)
```
uv venv .venv -p 3.11 && VIRTUAL_ENV=.venv uv pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m kb llm-smoke
```

Status: M0–M6 mini-flow works on macOS with the real Copilot model (4 samples: 22 verified facts, 47/47 citations, discrepancy found; answer in ~7 s). Windows: doctor passes, setup next.

> `pitch/assets/` (Example logo and product imagery, for the internal pitch only) is company property and is git-ignored.
