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
kb ingest                              # model builds pages; every quote is checked; one commit per source
kb ask "What is the minimum rest before a duty at home base?"
kb site --open                         # dashboard: sources, topics, discrepancies ⚖️, glossary, tokens
```
Expected: an answer citing `p. 3` of the OM and `t. 00:01:10` of the meeting, and one discrepancy (12 h vs 10 h).
Then with your own files: `kb add C:\path\to\document.pdf` (or drop files into `instance\inbox\` and run `kb collect inbox`).

### In GitHub Copilot CLI
Start `copilot` in this folder. It reads `AGENTS.md` and offers the skills `/kb-add`, `/kb-ingest`, `/kb-ask`,
`/kb-code`, `/kb-status`, `/kb-verify`. Ask normally ("what is the minimum rest at home base?"): Copilot runs
`kb ask` and repeats the citations. Allow the shell tool for `kb.cmd` when asked.

### Code questions
Clone a repository next to this one and list it in `instance\config\profile.yaml`:
```
code_repos:
  - {name: rules, path: ../my-repo, ref: main}
```
Then `kb code-ask "How is minimum rest computed? EXA-142" --evidence` (or `/kb-code` in Copilot): the answer cites
`repo/path:line@commit`. Try it on the sample: `samples\code-repo` (run `git init` + commit there first).

### All commands
`add`, `collect inbox|git|jira`, `ingest`, `ask`, `code-ask`, `search`, `verify`, `site`, `status`, `secrets set|check`, `login`, `llm-smoke`, `plugins`.

## Documentation
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
