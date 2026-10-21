# woynich-wiki

`woynich-wiki` (codename) is a **project knowledge base with a paper trail**. It collects project sources (documents, Jira, code, transcripts), keeps the originals, and builds a read-only wiki (the "LLM Wiki" pattern) in which every statement links to its exact source.

This repository is the **blueprint**: generic code, templates and instructions with no project data.

## Quick start on Windows (no admin rights)
1. Download the repository (GitHub → Code → **Download ZIP**, or `git clone`) and unpack it into a **short path outside
   OneDrive**, e.g. `C:\kb\woynich-wiki`. A ZIP copy is fine: setup connects it to this repository so updates work.
2. Double-click **`doctor.cmd`**. It is a read-only check of the machine that changes nothing. If it reports blockers, send `doctor-report.json`.
3. Double-click **`setup.cmd`**. It installs a private Python and the packages, finds or unpacks Git, downloads the
   Copilot runtime and puts a **Wiki** shortcut on the desktop and in the Start menu. Safe to run again.
4. Start **Wiki** (the shortcut, or `Wiki.cmd` in the folder). It starts the app (`kb serve`)
   in the browser; keep its window open. The first start
   creates the knowledge base instance (`instance\`, its own git repository) and opens a short **setup**: sign in to
   GitHub Copilot, choose the model (gpt-6-luna preselected when your account offers it), Jira and code repositories
   (both optional). Settings → "Run the first-run setup again" opens it later.
   Another knowledge base: `"Wiki.cmd" C:\kb\other-instance` (sets `KB_INSTANCE` for that window only).

In a terminal the same steps are `kb login` (Copilot sign-in), `kb llm-smoke` (checks that scripts can use the model;
send `instance\reports\llm-smoke.json`), `kb init` and `kb serve`.

| Script | What it does |
|---|---|
| `doctor.cmd` | read-only check of the machine (PowerShell, policies, proxy, Python, Git, Copilot); changes nothing |
| `setup.cmd` | private Python and packages, Git, Copilot runtime, `kb.cmd`, shortcut, 5 smoke tests (`-FullTest`: all); safe to run again |
| `Wiki.cmd [instance folder]` | starts the app in the browser; the first start opens the setup; restarts it after an update; offers an update when the app fails to start |
| `update.cmd` | downloads and installs the newest version (the same as Update in the app) |
| `test.cmd [pytest options]` | runs every test (setup runs only the 5 smoke tests); e.g. `test.cmd -k update` |
| `kb.cmd <command>` | the command line (created by setup); each copy of the repository runs its own code and instance |

The app's version and commit are under the status line in the sidebar; a click opens **About**, where *Collect diagnostics*
gathers versions, paths, the model, counts, which keys are set (never their values), a Copilot and Jira check and the last
errors, to copy or download for support. In a terminal: `kb diagnostics` (saved as `instance\reports\diagnostics.json`).

**Updates.** The app checks this repository at start and every hour; a new version shows as *Update available* in the
sidebar. About → **Update now** downloads it, keeps the knowledge base, settings and keys, installs changed packages and
restarts the app (it waits while sources are being added or an answer is being written); **Roll back to previous** undoes the last update. When the app does not start at all, its window offers
to update (press U), or run `update.cmd`. Terminal: `kb update [--check | --rollback]`. The source is `update` in
`setup/sources.json` (change it for a company mirror). About → **Changelog** lists what changed in each version, read from
Git history (`kb changelog [--all] [--md]`).

**Changes and versions.** Nothing is committed to `main` directly: every change is a pull request that CI checks
(all tests on Linux and Windows, the real `setup.ps1` on Windows) and that bumps `version` in `pyproject.toml`: patch for
every change, minor for a big new feature, major for a release. Each merge is one version that users get through Update.

The shortcut's icon is `instance\branding\icon.ico` or `icon.png` when the knowledge base has branding (kept out of Git),
otherwise a neutral one; after adding branding run `setup.cmd` again.

## First test: from a PDF to a cited answer (about 5 minutes)
```
kb add samples\sources                 # fictional Example Air sources: OM PDF, meeting, Jira ticket, e-mail
kb ingest                              # the model reads each source and writes the wiki; checks; one commit per source
kb ask "What is the minimum rest before a duty at home base?"
kb site --open                         # dashboard: sources, topics, discrepancies ⚖️, glossary, tokens
```
Expected: pages for the sources and concepts (e.g. minimum rest at home base), an answer citing `p. 3` of the OM and
`t. 00:01:10` of the meeting, and a contradiction (12 h vs 10 h). Each source and each question costs AI credits (shown under answers, in `kb quota` and in the kb serve sidebar).
Then with your own files: `kb add C:\path\to\document.pdf` (or drop files into `instance\inbox\` and run `kb collect inbox`).

### Branding (optional)
Put a logo and a header background into `instance\branding\` (`logo.png` or `logo.svg`, `background.jpg`, and `icon.svg`/`icon.png`
for the assistant avatar and browser tab; a white logo
suits the dark header) and run `kb site`. The dashboard and the `kb serve` sidebar both use them. They are embedded into the single dashboard file; company imagery never goes into this repository.
Set the title in `instance\config\profile.yaml` (`instance: {title: "Orders Rules knowledge base"}`).

### In GitHub Copilot CLI
Start `copilot` in this folder. It reads `AGENTS.md` and offers the skills `/kb-add`, `/kb-ingest`, `/kb-ask`,
`/kb-code`, `/kb-status`, `/kb-verify`. Ask normally ("what is the minimum rest at home base?"): Copilot reads
the wiki itself (`instance/wiki/hot.md` → `index.md` → pages), keeps that context for follow-up questions, cites the
pages and checks its draft with `kb check-answer` before replying (ADR-0019). Allow `view`/`grep` on `instance/` and
the shell tool for `kb.cmd` when asked. Ingest still runs only through `kb ingest` (sandboxed).

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
  (paste a screenshot with Ctrl+V, toggle "Code" to include the repositories). On a new knowledge base `kb serve` starts
  with a **first-run setup** (GitHub Copilot sign-in, the model with gpt-6-luna preselected, Jira with where to create its token, code repositories); it can be
  run again from Settings. **Settings** in `kb serve`: model per
  task tier or one model for all, GitHub Copilot sign-in and quota, keys and tokens (Windows Credential Manager), Jira URL;
- Jira (read-only): `kb jira get PROJ-123` prints an issue (fields, links, custom fields, description, comments as
  `#cN`), `kb jira search "<JQL>"`, `kb jira add PROJ-123 --links` registers issues as sources (screenshots become
  figures, documents their own sources). Credentials: the Windows credential `copilot-jira` (as the jira-snapshot
  skill stores it) or Settings → Jira token; Jira URL in Settings. The assistant also fetches tickets while answering.

### All commands
`add`, `collect inbox|git|jira`, `jira get|search|add`, `check`, `diagnostics`, `ingest`, `ask`, `code-ask`, `chat`, `repos`, `lint`, `remove`, `rollback`, `serve`, `search`, `check-answer`, `verify`, `site`, `status`, `model list|set|show`, `secrets set|check`, `login`, `llm-smoke`, `plugins`.

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

## License
MIT, see [LICENSE](LICENSE).
