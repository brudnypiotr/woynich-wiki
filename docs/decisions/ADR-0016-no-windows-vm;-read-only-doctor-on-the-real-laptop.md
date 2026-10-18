---
id: ADR-0016
title: No Windows VM; read-only doctor on the real laptop
status: accepted
date: 2026-10-18
---

# ADR-0016: No Windows VM; read-only doctor on the real laptop

**Context.** The Mac is ARM; the work laptop is x64 with corporate policies a VM cannot reproduce.

**Decision.** Run `doctor.cmd` (read-only) on the real laptop before setup; optional Windows CI later for regression.

**Consequences.** Real blockers are found early; less infrastructure.
