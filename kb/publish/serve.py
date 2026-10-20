"""Local web app: `kb serve` (127.0.0.1 only, standard library, no extra packages).

- Add sources: upload files from the browser; each goes through visible steps (saved → text extracted → wiki written →
  checked → citations verified) as a background job, one at a time.
- Discuss: one long agent session per discussion (ADR-0019), kept in instance/sessions/<id>.json, can be saved as a
  wiki page.
- Settings: models, GitHub Copilot sign-in, keys and tokens (never sent back to the browser), Jira, title, code repositories.
- Wiki: the static dashboard, rebuilt on request and shown inside the app (`/dashboard?embed=1`).

Every request needs the session token printed at start, so other web pages open in the browser cannot call the local
API; only the app's own code under /static/ is public. This module is the facade; the parts live in kb.publish.server
and the browser app in kb/publish/web.
"""
from kb.publish.server.app import make_server, serve
from kb.publish.server.chat_api import close_live
from kb.publish.server.http import Handler
from kb.publish.server.ingest_api import QUEUE, STEPS, WRITE_LOCK, _done_turn

__all__ = ["Handler", "QUEUE", "STEPS", "WRITE_LOCK", "_done_turn", "close_live", "make_server", "serve"]
