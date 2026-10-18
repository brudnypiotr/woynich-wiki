---
id: ADR-0010
title: Large originals outside git
status: accepted
date: 2026-10-18
---

# ADR-0010: Large originals outside git

**Context.** A previous project grew to 6.8 GB of git history with binaries.

**Decision.** Originals above 20 MB live in `store/` addressed by SHA-256; git keeps the record and the hash.

**Consequences.** Repositories stay small; the store needs its own backup.
