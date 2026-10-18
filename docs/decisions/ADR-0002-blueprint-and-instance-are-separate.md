---
id: ADR-0002
title: Blueprint and instance are separate
status: accepted
date: 2026-10-18
---

# ADR-0002: Blueprint and instance are separate

**Context.** The tool must be shareable without leaking project data.

**Decision.** This repository contains only generic code, templates and docs. Project content lives in `instance/` and `store/`, which are never committed to the blueprint.

**Consequences.** An instance has its own repository or folder; upgrades of the blueprint must not touch instance data.
