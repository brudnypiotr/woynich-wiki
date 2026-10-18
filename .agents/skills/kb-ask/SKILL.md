---
name: kb-ask
description: Answer a question about the project, product, client rules or documentation from the woynich-wiki knowledge base, with exact citations. Use for any project/domain question such as "what is the rule for…", "where is … described", "what did we agree…".
allowed-tools: ["shell"]
---
1. Run `.\kb.cmd ask "<the user's question>"` (Windows) or `.venv/bin/python -m kb ask "<question>"`.
   The question may be translated to English if the sources are in English.
2. Give the answer from the output **with its citations unchanged**. Do not add facts that are not in the output.
3. If the output says "No answer found", say so plainly and suggest which kind of source could be added.
4. If the answer mentions disagreeing sources, point to `instance/wiki/discrepancies.md`.
5. If the user wants to keep the answer, re-run with `--save` (it becomes a wiki page and a commit).
6. Use `--evidence` to show what excerpts were read when the user asks "why" or "where from".
