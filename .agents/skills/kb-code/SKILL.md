---
name: kb-code
description: Answer a technical question about how the application works, using the wiki together with the configured code repositories (read-only), citing file:line@commit. Use for "how does X work in the code", "where is Y computed", "what does PROJ-123 change in the code".
allowed-tools: ["shell", "view"]
---
1. Run `.\kb.cmd code-ask "<question>" --evidence` (Windows) or `.venv/bin/python -m kb code-ask "<question>" --evidence`.
   Mention a Jira key in the question if relevant; the model can fetch the ticket if Jira is configured.
2. Present the answer with its citations unchanged (`repo/path:line@commit`, `[[wiki-page]]`, `PROJ-1#c2`).
3. You may open the cited lines (read-only) to show the code. Never modify code.
4. If no repositories are configured (`kb repos` says so), explain how to add them to `instance/config/profile.yaml`:
   `code_repos: [{name: ..., path: ..., description: what the repository contains and what to look for}]`.
