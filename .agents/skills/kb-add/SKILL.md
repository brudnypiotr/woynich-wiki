---
name: kb-add
description: Add a document, folder, Jira export, transcript or e-mail to the project knowledge base (woynich-wiki). Use when the user wants to add, upload, drop or register a source file.
allowed-tools: ["shell"]
---
1. Ask for the file or folder path if not given. Files dropped into `instance/inbox/` can be collected with `collect inbox`.
2. Run `.\kb.cmd add "<path>"` (Windows) or `.venv/bin/python -m kb add "<path>"`.
   For Jira: `kb collect jira --jql "<JQL>"`. For a repository: `kb collect git --path <repo> --glob "docs/**"`.
3. Report each line of the output (added / exists, id, status, title). Status `error` means the file could not be read: say which.
4. Offer to run `/kb-ingest` next. Do not edit any files yourself.
