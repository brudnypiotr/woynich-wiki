The source page `wiki/sources/{{source_slug}}.md` (source id {{source_id}}, "{{title}}") has been deleted because
the source was removed from the knowledge base. Clean up the wiki in `wiki/`:
1. Find every page that cites `[[{{source_slug}}]]` (use grep).
2. On each page, remove statements that are supported only by that source; keep statements that other sources
   also support and remove only the citation to `[[{{source_slug}}]]`. Remove contradiction callouts that are no
   longer contradictions. Delete a page only if nothing is left of it, and then remove links to it.
3. Update `wiki/index.md`, add a line at the top of `wiki/log.md`, and refresh `wiki/hot.md`.
Do not add new knowledge. Reply with `UPDATED:` and `DELETED:` lists.
- Pages live in `wiki/sources/`, `wiki/entities/`, `wiki/concepts/`, `wiki/decisions/` and `wiki/answers/`; a link `[[name]]` means the file `name.md` in one of them (find it with glob `wiki/**/name.md`).
