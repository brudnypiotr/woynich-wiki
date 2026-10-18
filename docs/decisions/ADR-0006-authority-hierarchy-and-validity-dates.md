---
id: ADR-0006
title: Authority hierarchy and validity dates
status: accepted
date: 2026-10-18
---

# ADR-0006: Authority hierarchy and validity dates

**Context.** Conflicts between documents, tickets and code are normal.

**Decision.** Each source has an authority level (configurable in `config/profile.yaml`) and a `valid_from` date; conflicts are shown as discrepancies, never resolved silently.

**Consequences.** Requires a little metadata per source; enables 'what was true on date X'.
