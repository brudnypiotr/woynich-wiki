# ADR-0018: The model writes the wiki (agent ingest), scripts check and commit

Status: accepted (2026-10-19) · Supersedes the page-building part of ADR-0005

## Context
The first real test (four knowledge-sharing transcripts) showed that v1, which builds pages from verified atomic
facts extracted per 6,000-character window, produces correct but useless pages ("Person X said …"). The design
turned a stochastic writer into a deterministic fact list. The personal wiki built with the Karpathy LLM Wiki
pattern (claude-obsidian `wiki-ingest`) reads much better: the model reads whole sources and writes source
summaries, entity and concept pages in prose, linked to each other and to the sources.

## Decision
- One **agent session per source**: the model gets file tools, reads the whole source and the existing wiki, and
  creates or updates pages (sources, entities, concepts, decisions, glossary, index, log, hot). No windows.
- **Sandbox in code:** read only inside the instance, write only inside `wiki/`; no shell, web, MCP or memory.
- **Scripts** register and extract sources (text with locators), run the session, check links and citations
  (warnings, not deletions), commit, and roll back on failure or cancel.
- Questions and lint are agent sessions too (questions read-only).
- Model: GPT-6 Luna for now; routing per task stays configurable for stronger models later.
- v1 stays available as `--mode facts`.

## Consequences
- Pages read like a wiki; knowledge compounds across sources; contradictions are marked by the model.
- About one premium request per source and per question (an agent session counts as one prompt), instead of one
  per window; token use per session is higher (tens of thousands).
- Correctness relies on the model plus checks; pages stay `draft` until reviewed; every change is a Git commit.
