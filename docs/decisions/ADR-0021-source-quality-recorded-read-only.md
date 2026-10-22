# ADR-0021: Source quality is assessed after every ingest and only recorded

Status: accepted (2026-10-23)

## Context
- Users can drop a whole folder. Folders hold everything: specifications next to drafts, duplicates, templates,
  meeting invitations, files from another project. Every file costs AI credits and adds pages.
- We want to filter that noise one day (skip, ask, ingest later), but we do not know yet what a reliable signal is.
  A filter built on a guess would silently drop the one document that mattered.

## Decision
1. **The ingest model assesses the source at the end of its reply** (`prompts/ingest.md`, step 9): relevance,
   novelty, specificity, reliability and text quality, each 1–5 with a reason pointing to the text, a verdict
   (`core`, `useful`, `marginal`, `noise`) and one sentence for a curator. The scale is anchored in the prompt so
   scores are comparable across sources. It costs no extra call: the model has just read the whole source and the wiki.
2. **The script measures what the ingest produced** (no model): pages created and updated, pages citing the source,
   citations and citations per 10,000 characters, and what extraction noticed (pages without text, empty or hidden
   slides, cut sheets). Judgement and measurement are stored side by side so they can be compared.
3. **Read-only.** Saved as `raw/<id>/assessment.json`, committed with the ingest, one line in the commit body, shown
   on the file's card in Add sources (verdict also in the folder tree) and listed by `kb assess` (`--json`, `--csv`,
   `--verdict`). Nothing is skipped, filtered or ranked by it. A missing or malformed assessment never fails an ingest.

## Consequences
- After a few folders we can see how verdicts relate to the measured yield and to what curators think, and only then
  decide on an action (e.g. assess before ingest with a cheap pass, ask before ingesting `noise`).
- The score is a snapshot at ingest time: novelty depends on what the wiki held then, and later sources add citations.
- The model judges its own input; it may be generous. The measured signals are the check on it.
