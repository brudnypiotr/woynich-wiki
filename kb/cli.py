"""Command line: `python -m kb <command>` (setup also creates a `kb.cmd` shim)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kb import __version__
from kb.core import config, registry
from kb.knowledge.catalog import INSTANCE_DIRS


def _out(a, data, text: str) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=1, default=str) if getattr(a, "json", False) else text)


def cmd_init(a) -> int:
    from kb.knowledge import catalog
    inst = catalog.init()
    print(f"instance ready: {inst}")
    return 0


def cmd_add(a) -> int:
    from kb.knowledge import catalog
    rc = 0
    for f in a.files:
        p = Path(f)
        files = sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]
        for x in files:
            if not x.exists():
                print(f"not found: {x}"); rc = 1; continue
            rec, created = catalog.add_file(x, title=a.title if len(files) == 1 and a.title else None,
                                            version=a.version, found_via=["manual"])
            print(f"{'added  ' if created else 'exists '} {rec['id']}  {rec['status']:<9} {rec['title']}")
            rc = rc or (1 if rec["status"] == "error" else 0)
    return rc


def cmd_collect(a) -> int:
    from kb.knowledge import catalog
    if a.what == "inbox":
        res = catalog.collect_inbox()
    elif a.what == "git":
        from kb.connectors import git_repo
        res = git_repo.collect(a.path, a.ref, a.glob or None, a.limit)
    else:
        from kb.connectors import jira
        cfg = (config.load("profile").get("jira") or {})
        if not cfg.get("base_url"):
            print("set jira.base_url (and jira.email for Jira Cloud) in instance/config/profile.yaml"); return 2
        res = jira.collect(a.jql, a.limit or 50, **cfg)
    for rec, created in res:
        print(f"{'added  ' if created else 'exists '} {rec['id']}  {rec['status']:<9} {rec['title']}")
    print(f"{sum(c for _, c in res)} new, {sum(not c for _, c in res)} already known")
    return 0


def cmd_ingest(a) -> int:
    from kb.knowledge import verify, wiki
    show = lambda step, detail: print(f"  {step}: {detail}", flush=True)
    try:
        res = wiki.ingest_pending(a.ids or None, progress=show)
    except KeyboardInterrupt:
        print("\ninterrupted: unfinished changes were rolled back; the source stays registered.\n"
              "Run `kb ingest` to continue, or `kb remove <id>` to delete it (`kb status --sources` lists ids).")
        return 130
    for r in res:
        print(f"ingested {r['id']}: {len(r['created'])} pages created, {len(r['updated'])} updated, "
              f"{r.get('premium')} premium request(s), {r.get('seconds')} s")
        if r.get("reply"):
            print("  " + r["reply"].strip().replace("\n", "\n  ")[:1500])
    if not res:
        print("nothing to ingest (all sources already ingested; pass ids to re-ingest)")
    v = verify.verify_all()
    print(f"check: {v['citations_ok']}/{v['citations']} citations found in sources, {v['broken_links']} broken links, "
          f"{v['uncited_lines']} long lines without citation, {v['contradictions']} contradictions")
    return 0


def _answer(a, focus: str) -> int:
    from kb.knowledge import chat
    res = chat.ask(" ".join(a.question), focus=focus, save=getattr(a, "save", False), attachments=a.image or [])
    text = res["answer_text"]
    if a.evidence:
        text += "\n\nRead: " + (", ".join(res["pages_read"]) or "-") + f"\nTools: {', '.join(res['tools_used'])}"
    if res.get("saved"):
        text += f"\n\nsaved: {res['saved']}"
    _out(a, res, text)
    return 0 if not res["not_found"] else 3


def cmd_ask(a) -> int:
    return _answer(a, "wiki")


def cmd_code_ask(a) -> int:
    return _answer(a, "code")


def cmd_chat(a) -> int:
    """Conversation in the terminal. Commands: /image <path> attaches a screenshot to the next question, /save saves
    the last answer as a wiki page, /exit ends."""
    from kb.knowledge import chat, wiki
    topic = " ".join(a.topic) if a.topic else None
    hist, pending = [], []
    print("Ask about the project, the product, the code or a Jira ticket. /image <path>, /save, /exit")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); return 0
        if not q:
            continue
        if q in ("/exit", "/quit"):
            return 0
        if q.startswith("/image "):
            p = Path(q[7:].strip().strip('"'))
            if p.is_file():
                pending.append(p); print(f"  attached {p.name} (sent with the next question)")
            else:
                print("  no such file")
            continue
        if q == "/save":
            if hist:
                print("  saved: " + str(wiki.save_answer(hist[-1]["question"], hist[-1]["answer_text"], kind="discussion")))
            continue
        res = chat.ask(q, history=hist, topic=topic, attachments=pending)
        pending = []
        print("\n" + res["answer_text"] + f"\n  ({res['seconds']} s, {res.get('premium')} premium request)")
        hist.append({"question": q, "answer_text": res["answer_text"]})


def cmd_search(a) -> int:
    from kb.knowledge import search
    search.rebuild()
    hits = search.search(" ".join(a.query), limit=a.limit, kind=None if a.pages else "source")
    _out(a, hits, "\n".join(f"{h['title']} · {h['locator'] or '-'}  [{h['source_id']}]\n    {h['text'][:200].replace(chr(10), ' ')}" for h in hits) or "no matches")
    return 0


def cmd_verify(a) -> int:
    from kb.knowledge import verify
    v = verify.verify_all()
    text = (f"{v['pages']} pages, {v['citations_ok']}/{v['citations']} citations found in sources, {v['broken_links']} broken links, "
            f"{v['uncited_lines']} long lines without citation, {v['contradictions']} contradictions")
    text += "".join(f"\n  {p['page']}:{p['line']}  {p['issue']}" for p in v["problems"][:50])
    _out(a, v, text)
    return 0 if not v["problems"] else 1


def cmd_site(a) -> int:
    from kb.publish import site
    p = site.build()
    print(f"dashboard: {p}")
    if a.open:
        import webbrowser
        webbrowser.open(p.resolve().as_uri())
    return 0


def cmd_quota(a) -> int:
    from kb.llm.gateway import Gateway
    gw = Gateway(adapter="copilot-sdk")
    try:
        q = gw.llm.inner.quota()
    except Exception as e:
        print(f"cannot read quota ({type(e).__name__}: {e})"); return 1
    used_here = 0.0
    met = config.paths().metering
    if met.exists():
        for line in met.read_text(encoding="utf-8").splitlines():
            used_here += json.loads(line).get("premium") or 0
    if a.json:
        print(json.dumps({"quota": q, "premium_used_by_kb": used_here}, indent=1)); return 0
    for k, v in q.items():
        ent = "unlimited" if v["entitlement"] == -1 else v["entitlement"]
        pct = f"{v['remaining_pct']:.1f}% left" if isinstance(v["remaining_pct"], (int, float)) else ""
        print(f"  {k:<22} used {v['used']} of {ent}  {pct}  resets {v['resets'][:10] or 'n/a'}")
    print(f"  premium requests used by this knowledge base (metered): {used_here:g}")
    return 0


def cmd_serve(a) -> int:
    from kb.publish import serve
    serve.serve(port=a.port, open_browser=not a.no_browser, adapter=a.adapter)
    return 0


def cmd_remove(a) -> int:
    from kb.knowledge import catalog
    rc = 0
    for sid in a.ids:
        try:
            r = catalog.remove(sid)
            print(f"removed {r['id']}  {r['title']}  (was {r['status_was']})")
            if r.get("cleanup"):
                print("  " + (r["cleanup"].get("error") or f"model cleaned {r['cleanup']['pages_citing']} page(s) that cited it"))
        except KeyError as e:
            print(e); rc = 1
    return rc


def cmd_repos(a) -> int:
    from kb.knowledge import chat
    rs = chat.repos()
    if not rs:
        print("no code repositories configured. Add to instance/config/profile.yaml:\n"
              "code_repos:\n  - name: inventory-service\n    path: C:/Users/you/DEV/inventory-service\n"
              "    description: Inventory backend; rules engine, orders. Look here for rule logic.")
        return 1
    for r in rs:
        state = "MISSING" if not r["exists"] else f"{r.get('branch') or '?'}@{r['commit'] or '?'}" + (" (local changes)" if r["dirty"] else "")
        print(f"  {r['name']:<18} {state:<24} {r['path']}\n  {'':<18} {r['description']}")
    return 0


def cmd_lint(a) -> int:
    from kb.knowledge import wiki
    r = wiki.lint()
    print(r["reply"])
    return 0


def cmd_rollback(a) -> int:
    from kb.knowledge import catalog
    paths = catalog.rollback()
    print(f"discarded {len(paths)} uncommitted file(s) in raw/ and wiki/" if paths else "nothing to roll back")
    return 0


def cmd_status(a) -> int:
    from collections import Counter
    from kb.knowledge import catalog
    srcs = catalog.all_sources()
    met = config.paths().metering
    tokens = calls = 0
    if met.exists():
        for line in met.read_text(encoding="utf-8").splitlines():
            e = json.loads(line); calls += 1; tokens += (e.get("tokens_in") or 0) + (e.get("tokens_out") or 0)
    if getattr(a, "sources", False):
        for r in srcs:
            print(f"{r['id']}  {r['status']:<9} {r['kind']:<10} {r['title']}")
        return 0
    data = {"instance": str(catalog.instance()), "sources": len(srcs), "by_status": dict(Counter(r["status"] for r in srcs)),
            "by_kind": dict(Counter(r["kind"] for r in srcs)), "model_calls": calls, "model_tokens": tokens}
    _out(a, data, "\n".join(f"{k}: {v}" for k, v in data.items()))
    return 0


def cmd_plugins(a) -> int:
    plugins = config.load("plugins")
    for kind, items in plugins.items():
        print(f"{kind}:")
        for name, spec in (items or {}).items():
            try:
                registry.resolve(spec); ok = "ok"
            except Exception as e:
                ok = f"cannot load ({type(e).__name__})"
            print(f"  {name:<16} {spec}  [{ok}]")
    return 0


def cmd_llm_smoke(a) -> int:
    from kb.llm import smoke
    report = smoke.run()
    print(smoke.summary(report))
    return 0 if any(e.get("ok") for e in report["adapters"].values()) else 1


def cmd_login(a) -> int:
    """Sign in to GitHub Copilot once. The SDK reuses the credentials stored by the Copilot CLI login
    (or COPILOT_GITHUB_TOKEN / GH_TOKEN). The runtime bundled with the SDK has no `login` command."""
    import shutil
    import subprocess
    cli = shutil.which("copilot")
    if cli:
        return subprocess.call([cli, "login"])
    print("GitHub Copilot CLI not found. Install it (winget install GitHub.Copilot, or npm i -g @github/copilot),\n"
          "run `copilot login` once, then `kb llm-smoke`. Alternative: set COPILOT_GITHUB_TOKEN for this user.")
    return 2


def cmd_model(a) -> int:
    import yaml
    from kb.llm.gateway import Gateway
    gw = Gateway(adapter=a.adapter)
    if a.action == "show":
        tier, model = gw.model_for("query")
        print(f"model used for all tasks: {model}" if gw.cfg.get("model_override") or __import__("os").environ.get("KB_MODEL")
              else f"per task tier, e.g. query -> {tier}: {model}")
        return 0
    try:
        models = gw.llm.inner.list_models()
    except Exception as e:
        models = None
        print(f"cannot list models ({type(e).__name__}: {e})")
    if a.action == "list":
        for m in models or []:
            print(f"  {m['id']:<28} {m.get('name') or '':<28} {m.get('policy') or ''}")
        return 0 if models else 1
    if not a.model:
        print("usage: kb model set <id or name>"); return 2
    if models:
        want = a.model.strip().lower()
        hit = next((m for m in models if want in (str(m["id"]).lower(), str(m.get("name") or "").lower())), None)
        if hit:
            a.model = hit["id"]
        elif not a.force:
            close = [m["id"] for m in models if want.replace(" ", "-") in str(m["id"]).lower() or want in str(m.get("name") or "").lower()]
            print(f"{a.model!r} is not an available model" + (f"; did you mean {close[0]!r}?" if close else "") +
                  "\nRun `kb model list`, or use --force to set it anyway.")
            return 1
    p = config.paths().instance / "config" / "models.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
    data["model_override"] = a.model
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"all tasks now use {a.model} ({p})")
    return 0


def cmd_secrets(a) -> int:
    store = registry.create("secret_stores", a.store)
    if a.action == "set":
        import getpass
        store.set(a.name, getpass.getpass(f"value for {a.name}: "))
        print(f"stored {a.name!r} in {a.store}")
    else:
        print("set" if store.get(a.name) else "not set")  # never print the secret itself
    return 0


def main(argv=None) -> int:
    # Copilot CLI and pipes capture our output: on Windows that would be cp1252 and fail on "·" or "⚖️".
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="kb", description="woynich-wiki knowledge base")
    ap.add_argument("--version", action="version", version=f"woynich-wiki {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the knowledge base instance (its own git repository)").set_defaults(fn=cmd_init)
    s = sub.add_parser("add", help="register files or folders as sources (one commit each)")
    s.add_argument("files", nargs="+"); s.add_argument("--title"); s.add_argument("--version"); s.set_defaults(fn=cmd_add)
    s = sub.add_parser("collect", help="collect sources: inbox folder, a git repository or Jira (JQL)")
    s.add_argument("what", choices=["inbox", "git", "jira"]); s.add_argument("--path"); s.add_argument("--ref", default="HEAD")
    s.add_argument("--glob", action="append"); s.add_argument("--jql"); s.add_argument("--limit", type=int); s.set_defaults(fn=cmd_collect)
    s = sub.add_parser("ingest", help="the model reads new sources and writes the wiki (one agent session per source)")
    s.add_argument("ids", nargs="*"); s.set_defaults(fn=cmd_ingest)
    sub.add_parser("lint", help="the model checks and repairs the wiki (links, index, duplicates, contradictions)").set_defaults(fn=cmd_lint)
    for name, fn, hlp in (("ask", cmd_ask, "ask the knowledge base (wiki first; code, Jira and images when needed)"),
                          ("code-ask", cmd_code_ask, "ask about the code in the configured repositories (cites file:line@commit)")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("question", nargs="+"); s.add_argument("--json", action="store_true")
        s.add_argument("--evidence", action="store_true", help="also print what was read")
        s.add_argument("--image", action="append", type=Path, help="attach a screenshot (repeatable)")
        if name == "ask":
            s.add_argument("--save", action="store_true", help="save the answer as a wiki page")
        s.set_defaults(fn=fn)
    s = sub.add_parser("chat", help="conversation with the knowledge base in the terminal (/image, /save, /exit)")
    s.add_argument("topic", nargs="*"); s.set_defaults(fn=cmd_chat)
    sub.add_parser("repos", help="list the code repositories the model may read").set_defaults(fn=cmd_repos)
    s = sub.add_parser("search", help="full-text search (no model)")
    s.add_argument("query", nargs="+"); s.add_argument("--limit", type=int, default=8); s.add_argument("--pages", action="store_true")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_search)
    s = sub.add_parser("verify", help="check links and citations on wiki pages (warnings only)"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("site", help="build the dashboard (instance/site/index.html)"); s.add_argument("--open", action="store_true"); s.set_defaults(fn=cmd_site)
    s = sub.add_parser("quota", help="your Copilot quota (premium requests left) and what kb used")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_quota)
    s = sub.add_parser("serve", help="local web app: add files with visible steps, discussion sessions, dashboard")
    s.add_argument("--port", type=int, default=8765); s.add_argument("--no-browser", action="store_true"); s.add_argument("--adapter")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("status", help="counts and model usage"); s.add_argument("--json", action="store_true")
    s.add_argument("--sources", action="store_true", help="list sources with id and status"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("remove", help="delete sources (original, text, source page); the model cleans pages that cited them; one commit")
    s.add_argument("ids", nargs="+"); s.set_defaults(fn=cmd_remove)
    sub.add_parser("rollback", help="discard uncommitted leftovers of an interrupted ingest").set_defaults(fn=cmd_rollback)
    sub.add_parser("plugins", help="list registered plugins").set_defaults(fn=cmd_plugins)
    sub.add_parser("login", help="sign in to GitHub Copilot (once)").set_defaults(fn=cmd_login)
    sub.add_parser("llm-smoke", help="spike S1: test model access from scripts").set_defaults(fn=cmd_llm_smoke)
    s = sub.add_parser("model", help="list models, or use one model for every task (kb model set <id>)")
    s.add_argument("action", choices=["list", "set", "show"]); s.add_argument("model", nargs="?")
    s.add_argument("--adapter"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_model)
    s = sub.add_parser("secrets", help="store or check a secret (Jira token, ...)")
    s.add_argument("action", choices=["set", "check"]); s.add_argument("name")
    s.add_argument("--store", default="keyring"); s.set_defaults(fn=cmd_secrets)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
