---
id: ADR-0003
title: Windows, no admin, Python per user
status: accepted
date: 2026-10-18
---

# ADR-0003: Windows, no admin, Python per user

**Context.** Target users have standard Windows laptops without admin rights and are often not technical.

**Decision.** Bootstrap with PowerShell 5.1 (`setup.cmd` → `setup.ps1`); install Python 3.12 per user from python.org (fallback: embeddable zip); everything else in Python.

**Consequences.** Corporate policy (AppLocker, proxy) can still block us; `doctor.ps1` detects this up front.
