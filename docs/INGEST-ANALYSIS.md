# Ingest analysis: why the pages read badly, and what to change

Trigger: first real test (four knowledge-sharing session transcripts). The facts were technically correct and
verified, but useless to a reader ("Person X said …"), and the pages did not read like a wiki.

## Two approaches side by side

| | LLM Wiki as in the personal vault (Karpathy pattern, claude-obsidian `wiki-ingest`) | woynich-wiki v1 (what we built) |
|---|---|---|
| Who writes the wiki | **the model**, as an author: reads the whole source, then creates or edits pages | **code** renders pages; the model fills small JSON fields |
| Unit of work | a whole source → typically **8–15 pages touched** | one 6,000-character window → up to 8 atomic "facts" |
| What the model sees | the entire source + the existing index and pages it updates | one window; later only the list of extracted facts |
| Page types | source summary, **entities** (people, systems, products), **concepts**, domain pages, overview | source page and "topic" pages only |
| Page body | prose with sections, explanations, `[[links]]` between pages | a 2–5 sentence synopsis + a bullet list of facts with quotes |
| Structure | emerges: the model decides which pages to create or update | fixed: 1–5 topics per source, chosen from the fact list |
| Provenance | per page and per claim via links to the source summary; contradictions as callouts; lint later | **every** fact needs a verbatim 5–30-word quote, checked by code; unverified facts are dropped |
| Existing pages | read and edited (knowledge compounds) | regenerated from facts (max 40 per topic), never edited as text |

## Diagnosis
Your observation is right, and it is **mainly the design, not the model**.

1. **Atomisation destroys meaning.** Knowledge in a knowledge-sharing session is spread over many utterances:
   an explanation, a question, a correction, an example. Cut into 6,000-character windows and turned into
   one-sentence facts, it loses the "how" and "why".
2. **The verbatim-quote rule pushes towards attribution.** Spoken sentences are colloquial and the only exact text
   is the speaker's line, so the safest fact a model can write is "Anna said …". The rule rewards quotable
   sentences, not useful knowledge.
3. **The model never writes the page.** It never sees the source and the page together, so it cannot explain,
   merge or restructure. Pages are lists, not articles.
4. **Fixed structure.** No pages for systems, rules, parameters, processes, decisions or people as owners of
   knowledge, and no links between pages. A reader cannot navigate.
5. **The cheap model adds to it**, but a stronger model in the same pipeline would still produce fact lists.

What worked and should stay: originals kept unchanged, catalog with one commit per source, citations to exact
locators, automatic checks, search, dashboard, `kb serve`, Copilot skills, cost metering.

## Proposal: ingest v2, "the model writes the wiki, code checks it"
Closer to Karpathy's LLM Wiki, keeping our provenance guarantees in a softer form.

1. **Read the whole source** (or large sections: a one-hour transcript is about 10–15k tokens). Transcripts are
   pre-processed: utterances merged into speaker turns, filler removed, timestamps kept.
2. **Source note** (1 call): the model writes what a newcomer needs to know from this source, as knowledge, not as
   reported speech ("The rule engine evaluates X before Y because …"). Attribution only where it matters:
   decisions, opinions, uncertainty, owners ("Anna owns the rest rules"). Inline citations to locators
   (`[t. 00:12:30]`, `[p. 3]`, `[#c2]`).
3. **Plan** (1 call): the model gets the source note and the wiki index (page names + one-line descriptions) and
   decides which pages to **create or update**: system/component, rule, parameter, process/how-to, concept,
   decision, person/team, glossary term. It may also propose merging or renaming pages.
4. **Write pages** (1 call per page, typically 3–8): the model gets the existing page, the plan item and the
   relevant source sections, and returns the **whole updated page** in Markdown: sections, explanations,
   `[[links]]`, inline citations. Pages belong to the model; history is in Git.
5. **Check** (code + 1 cheap call per page):
   - every citation must point to an existing source and locator (hard rule, as now);
   - exact values (numbers, limits, dates, parameter names) must appear in the cited section (code check);
   - a support check marks sentences not supported by their cited section with ⚠ instead of deleting them;
   - contradictions are written as callouts on both pages and collected on the Discrepancies page.
6. **Lint** later (stale pages, orphans, missing links), as in the Karpathy pattern.

Cost per source: about 1 + 1 + (3–8) + (3–8) calls, i.e. **8–18 premium requests**, roughly the same as v1 for a
short transcript and **much cheaper for long documents** (no call per window).

`ask` changes too: it reads the wiki pages first (as Karpathy's query does) and falls back to source sections.
v1 stays available as a "strict facts" mode for regulatory documents, if wanted.

## Model choice
Run the same four transcripts through v2 twice, once with GPT-6 Luna and once with a stronger model from the
list (e.g. Claude Sonnet 5.5 or GPT-6.1 Sol), and compare the pages side by side. Extra cost: about 40–60 premium
requests. Then decide per task: for example, the stronger model for "write page" only and Luna for the rest
(`config/models.yaml` already routes per task).

## Risks and controls
| Risk | Control |
|---|---|
| model invents or over-generalises | citations required, exact values checked, ⚠ marking, pages stay `draft` until reviewed |
| model rewrites good text badly | every page change is a Git commit; diff visible; `kb rollback` / revert |
| prompt injection from sources | unchanged: no tools in model sessions, output only as returned text, scripts write files |
| page sprawl | plan step sees the index and must prefer updating existing pages; lint later |
