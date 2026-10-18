---
id: ADR-0005
title: Full LLM Wiki with a weak model, with compensating controls
status: accepted
date: 2026-10-18
---

# ADR-0005: Full LLM Wiki with a weak model, with compensating controls

**Context.** Only one, weaker model is available. Compiled pages can persist errors.

**Decision.** Generate wiki pages from the start (owner's decision), but pages are `draft` until reviewed, the citation verifier runs after every ingest, and the share of unsupported sentences is measured. A stronger model later re-runs ingest on the same sources.

**Consequences.** Quality is visible and improvable without rework.
