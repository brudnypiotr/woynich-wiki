"""Scripted agent for tests: behaves like the model in an agent session, writing files inside wiki/ only."""
from __future__ import annotations

import re
from pathlib import Path

from kb.extractors.base import segments
from kb.knowledge.agent import AgentResult


class ScriptedAgent:
    def __init__(self, stop_after_reading=False):
        self.stop_after_reading = stop_after_reading
        self.prompts = []
        self.opened, self.closed, self.alive = [], [], set()  # long sessions (ADR-0019)

    def open(self, model, root, read_roots=(), tools=(), resume=None):
        """A long session: every send() is one question; resume works only for sessions still alive."""
        outer = self

        class Live:
            resumed = bool(resume and resume in outer.alive)
            id = resume if resumed else f"live-{len(outer.opened) + 1}"

            def send(self, task, attachments=(), progress=None, cancelled=None):
                return outer.run(task, model, root, write_dirs=(), progress=progress, read_roots=read_roots, tools=tools,
                                 attachments=attachments)

            def close(self):
                outer.closed.append(self.id)
        live = Live()
        self.opened.append(live.id); self.alive.add(live.id)
        return live

    def run(self, task, model, root, write_dirs=("wiki",), progress=None, cancelled=None, read_roots=(), tools=(), attachments=()):
        self.prompts.append(task)
        self.last = {"read_roots": list(read_roots), "tools": [t.name for t in tools], "attachments": list(attachments), "write_dirs": write_dirs}
        root = Path(root); w = root / "wiki"; tools = []
        say = progress or (lambda *_: None)
        if "QUESTION:" in task:
            say("thinking", "Start with hot.md and the index.")
            say("reading", "view wiki/index.md")
            q = task.split("QUESTION:", 1)[1].split("\n", 1)[0].lower()
            if "FOCUS: this is a question about the code" in task and read_roots:
                hits = [(f, i) for r in read_roots for f in Path(r).rglob("*.py")
                        for i, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if "MIN_REST_HOME_BASE_HOURS" in l]
                f, i = hits[0]
                rel = f.relative_to(Path(read_roots[0])).as_posix()
                return AgentResult(f"`required_hours` takes the larger of the parameter and the previous duty (rules/{rel}:{i}@abc1234).",
                                   0.1, model, 100, 10, 1.0, [{"tool": "rg", "ok": True, "why": "read", "paths": [str(f)]}])
            hits = [p for p in w.rglob("*.md") if any(word in p.read_text(encoding="utf-8").lower() for word in q.split() if len(word) > 4)]
            # deterministic on every OS: prefer the paged OM-A source (it has p. 3), whatever order rglob returns
            srcs = sorted((p for p in hits if p.parent.name == "sources"), key=lambda p: ("om-a" not in p.stem, p.stem))
            src = srcs[0] if srcs else None
            reply = (f"Minimum rest is 12 hours ([[{src.stem}]] p. 3; see [[minimum-rest]])." if src else
                     "NOT FOUND: the wiki has nothing on this; a policy document would help.")
            return AgentResult(reply, 0.1, model, 100, 10, 1.0, [{"tool": "view", "ok": True, "why": "read", "paths": ["wiki/index.md"]}])
        if "has been deleted because" in task:
            slug = re.search(r"source page `wiki/sources/(.+?)\.md`", task).group(1)
            for p in w.rglob("*.md"):
                t = p.read_text(encoding="utf-8")
                if f"[[{slug}]]" in t:
                    p.write_text("\n".join(l for l in t.splitlines() if f"[[{slug}]]" not in l) + "\n", encoding="utf-8")
            return AgentResult("UPDATED: pages", 0.1, model, 50, 5, 1.0, tools)
        if "keep a project knowledge base healthy" in task:
            (w / "meta").mkdir(exist_ok=True); (w / "meta" / "lint.md").write_text("# Lint\nAll good.\n", encoding="utf-8")
            return AgentResult("Lint done.", 0.1, model, 50, 5, 1.0, tools)
        sid = re.search(r"Source id: ([0-9a-f]{12})", task).group(1)
        slug = re.search(r"source page\*\* `wiki/sources/(.+?)\.md`", task).group(1)
        title = re.search(r"- Title: (.+)", task).group(1)
        say("reading", f"view raw/{sid}/text.md")
        if self.stop_after_reading or (cancelled and cancelled()):
            (w / "concepts").mkdir(exist_ok=True)
            (w / "concepts" / "half-written.md").write_text("partial\n", encoding="utf-8")
            return AgentResult("CANCELLED", 0.1, model, 10, 1, 1.0, tools)
        segs = segments((root / "raw" / sid / "text.md").read_text(encoding="utf-8"))
        loc = next((l for l, _ in segs if l and l != "top"), "top").replace("L", "L ")
        say("writing", f"create wiki/sources/{slug}.md")
        (w / "sources" / f"{slug}.md").write_text(
            f"---\ntype: source\nsource_id: {sid}\ntitle: \"{title}\"\nstatus: draft\n---\n# {title}\n\n"
            f"What this source says, as knowledge. ([[{slug}]] {loc})\n\n## Related pages\n[[minimum-rest]]\n", encoding="utf-8")
        c = w / "concepts" / "minimum-rest.md"
        old = c.read_text(encoding="utf-8") if c.exists() else "---\ntype: concept\nstatus: draft\n---\n# Minimum rest\n\n"
        c.write_text(old + f"- Knowledge from {title}. ([[{slug}]] {loc})\n", encoding="utf-8")
        txt = " ".join(t for _, t in segs)
        self.seen = getattr(self, "seen", set()) | {v for v in ("12 hours", "10 hours") if v in txt}
        if len(self.seen) == 2 and "[!contradiction]" not in c.read_text(encoding="utf-8"):
            c.write_text(c.read_text(encoding="utf-8") + "\n> [!contradiction] 12 hours vs 10 hours\n", encoding="utf-8")
        (w / "index.md").write_text("# Index\n\n" + "\n".join(f"- [[{p.stem}]]" for p in sorted(w.rglob("*.md")) if p.parent != w) + "\n", encoding="utf-8")
        (w / "log.md").write_text(f"# Log\n\n## ingest | {title}\n\n" + (w / "log.md").read_text(encoding="utf-8").split("\n\n", 1)[-1], encoding="utf-8")
        (w / "hot.md").write_text(f"# Recent context\n\nLatest: [[{slug}]].\n", encoding="utf-8")
        return AgentResult(f"CREATED: wiki/sources/{slug}.md\nUPDATED: wiki/concepts/minimum-rest.md", 0.2, model, 1000, 100, 1.0,
                           [{"tool": "create", "ok": True, "why": "write", "paths": [f"wiki/sources/{slug}.md"]}])
