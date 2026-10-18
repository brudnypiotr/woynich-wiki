---
id: ADR-0008
title: Full-text search with SQLite FTS5 first
status: accepted
date: 2026-10-18
---

# ADR-0008: Full-text search with SQLite FTS5 first

**Context.** A weak model cannot read everything; it must search first.

**Decision.** Index text chunks, pages and glossary in SQLite FTS5 (built into Python). Embedding search is an optional second adapter, added only if the gold question set shows FTS is not enough.

**Consequences.** No extra install, deterministic, no token cost.
