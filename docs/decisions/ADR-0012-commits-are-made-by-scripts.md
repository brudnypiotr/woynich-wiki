---
id: ADR-0012
title: Commits are made by scripts
status: accepted
date: 2026-10-18
---

# ADR-0012: Commits are made by scripts

**Context.** Editor/agent hooks differ between tools and created unreadable 'auto: update' history.

**Decision.** Every `kb` command that changes data makes one commit with a conventional message (`source(...)`, `ingest(...)`, `fix(...)`, `glossary(...)`, `decision(...)`). A pre-commit hook blocks secrets and invalid records.

**Consequences.** Readable, atomic history independent of the AI tool.
