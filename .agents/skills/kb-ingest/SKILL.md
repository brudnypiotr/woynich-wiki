---
name: kb-ingest
description: Build or update the knowledge base wiki pages from newly added sources (woynich-wiki ingest + citation check). Use after adding sources or when the user asks to process, ingest or update the wiki.
allowed-tools: ["shell"]
---
1. Run `.\kb.cmd ingest` (Windows) or `.venv/bin/python -m kb ingest`. It can take a few minutes; the model is called by the tool.
2. Report per source: verified facts, rejected facts, topics. Then report the `verify:` line.
3. If verify shows problems, run `kb verify` and list them. Never fix wiki pages by hand.
4. Mention discrepancies: read `instance/wiki/discrepancies.md` and summarise each line with its link.
5. Offer `kb site --open` to see the dashboard.
