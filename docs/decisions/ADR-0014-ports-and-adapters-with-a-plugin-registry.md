---
id: ADR-0014
title: Ports and adapters with a plugin registry
status: accepted
date: 2026-10-18
---

# ADR-0014: Ports and adapters with a plugin registry

**Context.** New sources (mailbox, OneDrive, Teams) and models will be added later.

**Decision.** The core depends on interfaces (Connector, Extractor, LLM, SecretStore, Publisher); implementations are registered in `config/plugins.yaml`. A test proves a new connector needs no core change.

**Consequences.** Extensible without rewrites.
