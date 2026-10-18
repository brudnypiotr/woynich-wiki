---
name: kb-status
description: Show the state of the woynich-wiki knowledge base: number of sources, ingest status, model usage and tokens, and open the dashboard.
allowed-tools: ["shell"]
---
1. Run `.\kb.cmd status` (Windows) or `.venv/bin/python -m kb status`.
2. Summarise in 3–5 lines: sources by status and kind, model calls and tokens.
3. Run `kb site --open` if the user wants the dashboard (overview, sources, topics, discrepancies, glossary, usage, questions).
