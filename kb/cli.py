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
    from kb.knowledge import ingest, verify
    from kb.llm.gateway import Gateway
    res = ingest.ingest_pending(Gateway(adapter=a.adapter), a.ids or None)
    for r in res:
        print(f"ingested {r['id']}: {r['claims']} verified facts, {r['rejected']} rejected, topics: {', '.join(r['topics']) or '-'}")
    if not res:
        print("nothing to ingest (all sources already ingested; pass ids to re-ingest)")
    v = verify.verify_all()
    print(f"verify: {v['ok']}/{v['facts']} citations ok, {len(v['problems'])} problems")
    return 0 if not v["problems"] else 1


def cmd_ask(a) -> int:
    from kb.knowledge import ask
    from kb.llm.gateway import Gateway
    q = " ".join(a.question)
    res = ask.answer(q, Gateway(adapter=a.adapter), save=a.save)
    text = ask.render(res, rel=str(Path(config.paths().instance / "wiki").resolve().as_posix()))
    if a.evidence and res["evidence"]:
        text += "\n\nEvidence:\n" + "\n".join(f"[{i}] {e['title']} · {e['locator']}: {e['text'][:200]}" for i, e in enumerate(res["evidence"], 1))
    if res.get("saved"):
        text += f"\n\nsaved: {res['saved']}"
    _out(a, res, text)
    return 0 if not res["not_found"] else 3


def cmd_code_ask(a) -> int:
    from kb.knowledge import code
    from kb.llm.gateway import Gateway
    res = code.code_ask(" ".join(a.question), Gateway(adapter=a.adapter))
    text = code.render(res)
    if a.evidence and res.get("snippets"):
        text += "\n\nSnippets read:\n" + "\n".join(f"[{i}] {s['repo']}/{s['path']}:{s['hit_line']} (term: {s['term']})" for i, s in enumerate(res["snippets"], 1))
    _out(a, res, text)
    return 0 if not res["not_found"] else 3


def cmd_search(a) -> int:
    from kb.knowledge import search
    search.rebuild()
    hits = search.search(" ".join(a.query), limit=a.limit, kind=None if a.pages else "source")
    _out(a, hits, "\n".join(f"{h['title']} · {h['locator'] or '-'}  [{h['source_id']}]\n    {h['text'][:200].replace(chr(10), ' ')}" for h in hits) or "no matches")
    return 0


def cmd_verify(a) -> int:
    from kb.knowledge import verify
    v = verify.verify_all()
    text = f"{v['pages']} pages, {v['facts']} cited facts, {v['ok']} verified, {len(v['problems'])} problems"
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


def cmd_status(a) -> int:
    from collections import Counter
    from kb.knowledge import catalog
    srcs = catalog.all_sources()
    met = config.paths().metering
    tokens = calls = 0
    if met.exists():
        for line in met.read_text(encoding="utf-8").splitlines():
            e = json.loads(line); calls += 1; tokens += (e.get("tokens_in") or 0) + (e.get("tokens_out") or 0)
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
    s = sub.add_parser("ingest", help="build wiki pages from new sources (model + quote verification)")
    s.add_argument("ids", nargs="*"); s.add_argument("--adapter"); s.set_defaults(fn=cmd_ingest)
    for name, fn, hlp in (("ask", cmd_ask, "answer a question from the knowledge base, with citations"),
                          ("code-ask", cmd_code_ask, "answer a technical question from the configured code repositories")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("question", nargs="+"); s.add_argument("--adapter"); s.add_argument("--json", action="store_true")
        s.add_argument("--evidence", action="store_true", help="also print what was read")
        if name == "ask":
            s.add_argument("--save", action="store_true", help="save the answer as a wiki page")
        s.set_defaults(fn=fn)
    s = sub.add_parser("search", help="full-text search (no model)")
    s.add_argument("query", nargs="+"); s.add_argument("--limit", type=int, default=8); s.add_argument("--pages", action="store_true")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_search)
    s = sub.add_parser("verify", help="check every citation and quote on wiki pages"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("site", help="build the dashboard (instance/site/index.html)"); s.add_argument("--open", action="store_true"); s.set_defaults(fn=cmd_site)
    s = sub.add_parser("status", help="counts and model usage"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_status)
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
