---
id: ADR-0013
title: Secrets in Windows Credential Manager
status: accepted
date: 2026-10-18
---

# ADR-0013: Secrets in Windows Credential Manager

**Context.** Jira and Microsoft Graph need tokens.

**Decision.** Store secrets with `keyring` (Credential Manager, per user, no admin); environment variables as read-only fallback; never in the repository.

**Consequences.** Users run `kb secrets set jira` once.
