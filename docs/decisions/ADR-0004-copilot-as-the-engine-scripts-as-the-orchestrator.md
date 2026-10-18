---
id: ADR-0004
title: Copilot as the engine, scripts as the orchestrator
status: accepted
date: 2026-10-18
note: replaces D4 (agent-driven)
---

# ADR-0004: Copilot as the engine, scripts as the orchestrator

**Context.** Copilot can be driven from code: the Python SDK (`github-copilot-sdk`) and `copilot -p` (JSONL output, usage file). Verified on macOS (spike S1).

**Decision.** Pipelines call the model through `kb.llm.gateway`; SDK adapter is the default, CLI adapter the fallback. The agent (skills) is used for Q&A and ad-hoc work, not for running the pipeline.

**Consequences.** Repeatable runs, metering and budgets in one place; works the same for any user.
