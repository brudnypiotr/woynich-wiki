# ADR-0020: The web app as static ES modules, a route table, shared settings parts

Status: accepted (2026-10-20)

## Context
- `kb/publish/serve.py` had grown to 1060 lines: the HTTP server, the ingest queue, the discussion sessions and the
  whole browser app (about 500 lines of HTML, CSS and JS in one Python string). Routing was a chain of
  `if url.path == …` in `do_GET` and `do_POST`.
- A first-run setup (Copilot sign-in, Jira, repositories) needs the same pieces as Settings; with one inline Settings
  block it would have meant copying them.
- The work laptop has no admin rights: no npm, no bundler, no build step. Whatever the app uses must run from the
  files as they are.

## Decision
1. **The browser app lives in `kb/publish/web/` as plain files**: `index.html` (a template the server fills: title,
   logo, favicon, a JSON config with the session token), `app.css` and native **ES modules** in `js/` (`ui`, `api`,
   `markdown`, `shell`, `trace`, `chat`, `uploads`, `wiki`, `settings`, `setup`, `main`). No build step.
2. **`/static/` is served without the token** (code only, no data; the server listens on 127.0.0.1) with an explicit
   MIME map: Python's `mimetypes` reads the Windows registry, which can map `.js` to `text/plain` and break modules.
   Everything else still needs the token.
3. **A route table instead of if-chains**: `@route(method, pattern)` in `kb/publish/server/http.py`; handlers in topic
   modules (`web`, `chat_api`, `ingest_api`, `settings_api`); errors map to JSON in one place (400/404/500).
   `kb/publish/serve.py` stays as the facade the CLI and tests import.
4. **Settings sections are parts** (`web/js/parts/`: copilot, jira, repos, shared checks and secret rows), each a
   function `mountX(el, settingsState)` that returns what its host needs (`save()`, `ok()`). Settings and the
   first-run setup mount the same parts, so a change lands in both.
5. **Module state stays private**: the open discussion and the answer in progress live in `chat.js`; other modules
   ask through exported functions. Inline handlers that reached for globals became event delegation.

## Consequences
- Each file has one job and fits on a few screens; a new view or API is a new module plus one import.
- The JS is readable in the browser's dev tools as written; `node --check` catches syntax errors per file.
- Browsers cache nothing (`Cache-Control: no-store`), so an update is picked up on reload.
- The model choice is a part too (`parts/model.js`): Settings mounts it, and the first-run setup has a model step
  after the Copilot sign-in that preselects `recommended_model` (gpt-6-luna) when the account offers it.
- Not done yet: `kb/publish/site.py` (the dashboard) still builds its HTML in Python.
