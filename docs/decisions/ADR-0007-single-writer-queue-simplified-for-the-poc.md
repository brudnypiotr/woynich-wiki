---
id: ADR-0007
title: Single-writer queue, simplified for the PoC
status: accepted
date: 2026-10-18
note: simplifies D10
---

# ADR-0007: Single-writer queue, simplified for the PoC

**Context.** Parallel writers corrupt state; the PoC has one curator.

**Decision.** Submissions are files in `queue/` in the final format; `kb process` applies them serially. No service yet.

**Consequences.** The same queue can later sit behind an API or mailbox.
