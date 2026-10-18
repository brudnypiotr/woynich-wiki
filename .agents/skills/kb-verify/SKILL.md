---
name: kb-verify
description: Check that every citation and quote on the woynich-wiki pages matches its source. Use when the user asks if the wiki can be trusted or after manual changes.
allowed-tools: ["shell"]
---
1. Run `.\kb.cmd verify` (Windows) or `.venv/bin/python -m kb verify`.
2. Report: pages, cited facts, verified, problems. List problems with page and line.
3. Problems mean a page no longer matches its source: suggest `kb ingest <source id>` to rebuild it. Do not edit pages.
