---
name: kb-ingest
description: Let the model read newly added sources and write or update the knowledge base wiki pages (woynich-wiki ingest + checks). Use after adding sources or when the user asks to process, ingest or update the wiki.
allowed-tools: ["shell"]
---
1. Run `.\kb.cmd ingest` (Windows) or `.venv/bin/python -m kb ingest`. It can take a few minutes; the model is called by the tool.
2. Report per source: pages created and updated, premium requests used. Then report the `check:` line
   (citations found in sources, broken links, contradictions). Interrupt with Ctrl+C: changes are rolled back.
3. If verify shows problems, run `kb verify` and list them. Never fix wiki pages by hand.
4. Mention contradictions: search `instance/wiki` for `[!contradiction]` and summarise each with its page.
5. Offer `kb site --open` to see the dashboard.
