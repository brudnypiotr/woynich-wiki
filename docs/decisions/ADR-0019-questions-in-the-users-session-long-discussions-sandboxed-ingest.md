# ADR-0019: Questions in the user's own agent session, long discussions, ingest stays sandboxed

Status: accepted (2026-10-19) · Amends ADR-0018 (questions)

## Context
- The Copilot CLI skill `/kb-ask` ran `kb ask`, which opened a **second** agent session (SDK) for every question:
  one premium request for the user's prompt in the CLI plus one for the nested session. The nested session also
  started cold: it re-read `index.md` and the same pages for every follow-up question, and its context was lost.
- In `kb serve` every question in a discussion was a new session; the earlier turns came back only as text.
- The personal wiki (claude-obsidian) works the other way: the agent the user is already talking to reads
  `hot.md` → `index.md` → pages itself, and the context it builds stays for the whole conversation. That context is
  where most of the value comes from.

## Decision
1. **Questions in the Copilot CLI are answered by the CLI agent itself.** The skills (`kb-ask`, `kb-code`) and
   `AGENTS.md` tell it to read `instance/wiki` (hot → index → pages → `raw/<id>/text.md` for exact wording) and the
   configured code repositories, cite `[[page]]`, `([[source]] p. 3)`, `repo/path:line@commit`, and run
   **`kb check-answer`** (deterministic, no model) on its draft before replying. `kb ask` stays for scripts and for
   users without an agent, but the skills no longer call it.
2. **One long agent session per discussion in `kb serve` (and `kb chat`).** Follow-up questions are sent to the
   same session, so the model keeps what it has read. The session id is stored with the discussion and resumed
   after a restart (SDK `resume_session`); if that fails, a new session starts with a summary of the earlier turns.
   Idle sessions are closed after 30 minutes; changing the model in Settings closes them.
3. **After an ingest, open discussions are told which pages changed** (a short note in front of the next question),
   so the model re-reads them instead of trusting what it remembers.
4. **Ingest stays in the sandboxed SDK session** (ADR-0018): sources are untrusted data (prompt injection in e-mails,
   tickets, pages), and only the sandbox guarantees "read the instance, write only `wiki/`, no shell". The CLI agent
   has a shell, so it must not ingest; rule 2 in `AGENTS.md` (never edit `instance/wiki` or `instance/raw`) stays.

## Consequences
- CLI: one premium request per prompt instead of two; follow-ups reuse the context.
- `kb serve`: still one premium request per question (billing counts prompts, not sessions), but fewer tokens and
  more consistent answers, because the model does not start from zero.
- Citation checking moves from "the nested tool checked it" to "the agent must run `kb check-answer`" — enforced
  by instructions, not code. The check itself is deterministic.
- Long sessions can hold stale context (mitigated by the change note) and fill the context window (the runtime
  compacts; very long discussions lose detail — start a new one).
- To measure: the same 5 questions through the CLI skill, `kb serve` and `kb ask`, comparing quota before/after
  with `premium` in `catalog/metering.jsonl`.
