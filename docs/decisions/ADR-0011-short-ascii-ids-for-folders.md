---
id: ADR-0011
title: Short ASCII ids for folders
status: accepted
date: 2026-10-18
---

# ADR-0011: Short ASCII ids for folders

**Context.** Windows has a 260-character path limit; human keys were assigned before metadata existed.

**Decision.** Folder names are 12-character ids; human-readable keys live in metadata and can change.

**Consequences.** Stable paths; renaming a key never moves files.
