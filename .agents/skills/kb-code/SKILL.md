---
name: kb-code
description: Answer a technical question about how the application works, from the configured source code repositories (woynich-wiki code-ask), with path:line@commit citations. Use for "how does X work in the code", "where is Y computed", "what does JIRA-123 change in the code".
allowed-tools: ["shell", "view"]
---
1. Run `.\kb.cmd code-ask "<question>" --evidence` (Windows) or `.venv/bin/python -m kb code-ask "<question>" --evidence`.
   Include a Jira key in the question if the user mentions one; the tool adds the ticket text from the knowledge base.
2. Present the answer with its `repo/path:line@commit` citations unchanged.
3. You may open the cited files at those lines (read-only) to show the relevant code to the user. Never modify code.
4. If nothing is found, show the searched terms and ask the user for a class, method or parameter name to try.
5. If `no code repositories configured`, explain: add `code_repos: [{name: ..., path: ..., ref: main}]` to `instance/config/profile.yaml`.
