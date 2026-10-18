---
id: ADR-0001
title: Provenance on every statement
status: accepted
date: 2026-10-18
---

# ADR-0001: Provenance on every statement

**Context.** A knowledge base built by a model is only useful if every statement can be checked.

**Decision.** Every statement in the wiki carries a source and a machine-checkable locator (page, paragraph, comment, file:line@commit, time stamp); key claims carry a verbatim quote.

**Consequences.** Ingest is slower and stricter; in exchange answers are auditable and errors are fixable.
