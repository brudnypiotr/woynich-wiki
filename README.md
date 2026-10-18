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
   - `kb init`: creates the instance folders

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

Status: M0 (foundation) done, M1 (setup and doctor) ready for testing on Windows.

> `pitch/assets/` (Example logo and product imagery, for the internal pitch only) is company property and is git-ignored.
