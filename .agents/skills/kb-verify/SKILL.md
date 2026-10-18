---
name: kb-verify
description: Check that links and citations on the woynich-wiki pages point to existing pages and to existing places in the sources. Use when the user asks if the wiki can be trusted or after a large ingest.
allowed-tools: ["shell"]
---
1. Run `.\kb.cmd verify` (Windows) or `.venv/bin/python -m kb verify`.
2. Report: pages, citations found in sources, broken links, long lines without citation, contradictions; list problems.
3. Problems are warnings. Suggest `kb lint` (the model repairs links, index and duplicates) or re-ingesting a source.
   Never edit pages yourself.
