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


def cmd_jira(a) -> int:
    """Jira, read-only: `get` prints one issue (nothing stored), `search` lists keys, `add` registers issues as sources."""
    from kb.connectors import jira
    cfg = config.load("profile").get("jira") or {}
    try:
        if a.action == "get":
            from kb.knowledge.tools.jira import images_dir
            for k in a.args:  # pictures to the instance's cache, absolute paths: the CLI model looks at them with view
                print(jira.get_text(k, images=None if a.no_images else images_dir(), **cfg))
        elif a.action == "search":
            for i in jira.Jira(**cfg).search(" ".join(a.args), a.limit or 20):
                print(f"{i['key']}: {i['fields'].get('summary', '')} [{(i['fields'].get('status') or {}).get('name', '')}]")
        else:
            res = jira.add(a.args, links=a.links, attachments=not a.no_attachments, **cfg)
            for r in res:
                rec = r["record"]
                print(f"{'added  ' if r['created'] else 'exists '} {rec['id']}  {rec['title']}"
                      + (f"  (+{r['figures']} screenshots, {len(r['attachments'])} document attachments)" if r["created"] else ""))
                for w in r["warnings"]:
                    print(f"  warning: {w}")
            print(f"{sum(r['created'] for r in res)} new. Next: `kb ingest` (or Add sources in kb serve) writes them into the wiki.")
    except (RuntimeError, PermissionError, ValueError) as e:
        print(f"Jira: {e}")
        return 2
    return 0


def cmd_check(a) -> int:
    """Heartbeat: are the GitHub Copilot sign-in and the Jira token valid? No AI credits used."""
    from kb.llm.gateway import Gateway
    from kb.publish import settings
    r = settings.check(Gateway(adapter=a.adapter))
    for k, v in r.items():
        print(f"{'OK  ' if v['ok'] else ('FAIL' if v['ok'] is False else '--  ')} {k:<8} {v['detail']}")
    return 1 if any(v["ok"] is False for v in r.values()) else 0


def cmd_diagnostics(a) -> int:
    """Version and technical state for support (no keys, no content), saved to instance/reports/diagnostics.json."""
    from kb.llm.gateway import Gateway
    from kb.publish import diagnostics
    r = diagnostics.report(Gateway(adapter=a.adapter))
    out = config.paths().reports / "diagnostics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(diagnostics.as_text(r), encoding="utf-8")
    v = r["app"]
    print(f"woynich-wiki {v['version']} ({v['commit'] or 'no git'}{', local changes' if v['dirty'] else ''}) · {r['runtime']['os']}")
    for k, c in r["checks"].items():
        print(f"{'OK  ' if c['ok'] else ('FAIL' if c['ok'] is False else '--  ')} {k:<8} {c['detail']}")
    print(f"saved: {out}  (send this file for help; it has no keys and no content)")
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
              f"{_credits(r.get('credits'))}, {r.get('seconds')} s")
        if r.get("reply"):
            print("  " + r["reply"].strip().replace("\n", "\n  ")[:1500])
    if not res:
        print("nothing to ingest (all sources already ingested; pass ids to re-ingest)")
    v = verify.verify_all()
    print(f"check: {v['citations_ok']}/{v['citations']} citations found in sources, {v['broken_links']} broken links, "
          f"{v['uncited_lines']} long lines without citation, {v['contradictions']} contradictions")
    return 0


def _credits(v) -> str:
    return "AI credits n/a" if v is None else f"{v:.2f} AI credits"


def _check_line(res: dict) -> str:
    c = res.get("check") or {}
    if not c.get("ok") and not c.get("broken"):
        return ""
    return (f"\n  citations checked: {len(c['ok'])} ok" + (f", {len(c['broken'])} BROKEN: " + "; ".join(c["broken"][:5]) if c["broken"] else ""))


def _answer(a, focus: str) -> int:
    from kb.knowledge import chat
    res = chat.ask(" ".join(a.question), focus=focus, save=getattr(a, "save", False), attachments=a.image or [])
    text = res["answer_text"]
    if a.evidence:
        text += "\n\nRead: " + (", ".join(res["pages_read"]) or "-") + f"\nTools: {', '.join(res['tools_used'])}"
    if res.get("saved"):
        text += f"\n\nsaved: {res['saved']}"
    text += _check_line(res)
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
    conv, pending = chat.Conversation(topic=topic), []
    print("Ask about the project, the product, the code or a Jira ticket. /image <path>, /save, /exit")
    try:
        return _chat_loop(conv, pending, wiki)
    finally:
        conv.close()


def _chat_loop(conv, pending, wiki) -> int:
    hist = conv.history
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
        res = conv.ask(q, attachments=pending)  # one session for the whole chat (ADR-0019)
        pending.clear()
        print("\n" + res["answer_text"] + f"\n  ({res['seconds']} s, {_credits(res.get('credits'))}, {res['session']} session)"
              + _check_line(res))


def cmd_search(a) -> int:
    from kb.knowledge import search
    search.rebuild()
    hits = search.search(" ".join(a.query), limit=a.limit, kind=None if a.pages else "source")
    _out(a, hits, "\n".join(f"{h['title']} · {h['locator'] or '-'}  [{h['source_id']}]\n    {h['text'][:200].replace(chr(10), ' ')}" for h in hits) or "no matches")
    return 0


def cmd_check_answer(a) -> int:
    """Check the citations of an answer before showing it (used by the Copilot CLI skills, ADR-0019)."""
    from kb.knowledge import verify
    if a.file:
        text = Path(a.file).read_text(encoding="utf-8", errors="replace")
    elif a.text and a.text != ["-"]:
        text = " ".join(a.text)
    else:
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    r = verify.check_answer(text)
    lines = [f"{len(r['ok'])} citations OK, {len(r['broken'])} broken, {len(r['unchecked'])} Jira references not checked, "
             f"{r['uncited_lines']} long lines without a citation"]
    lines += [f"  BROKEN  {b}" for b in r["broken"]] + [f"  ok      {o}" for o in r["ok"]] + [f"  jira    {j}" for j in r["unchecked"]]
    if r["broken"]:
        lines.append("Fix or remove the broken citations (re-read the page or source), then check again.")
    _out(a, r, "\n".join(lines))
    return 1 if r["broken"] else 0


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
    """Where you are in the billing cycle: AI credits (or premium requests on legacy plans), reset, days left."""
    from kb.llm.gateway import Gateway
    from kb.publish import settings
    u = settings.usage(Gateway(adapter="copilot-sdk"))
    if a.json:
        print(json.dumps(u, indent=1)); return 0
    if u["entitlement"] is not None and not u["unlimited"]:
        print(f"  {u['unit']}: {u['used']:g} of {u['entitlement']:g} used ({100 - (u['remaining_pct'] or 0):.0f}%)"
              + (f", plan {u['plan']}" if u["plan"] else ""))
    elif u["unlimited"]:
        print(f"  {u['unit']}: unlimited")
    else:
        print(f"  quota not available from GitHub ({u['error']})")
    print(f"  resets {u['reset'][:10]} (00:00 UTC): {u['days_left']} days, {u['business_days_left']} working days")
    print(f"  used by this knowledge base this month: {u['kb_month']:g} AI credits")
    return 0

def cmd_serve(a) -> int:
    from kb.publish import serve
    return serve.serve(port=a.port, open_browser=not a.no_browser, adapter=a.adapter)


def cmd_update(a) -> int:
    """Update this copy from its Git remote (what the Update button does), check only, roll back, or finish (packages)."""
    from kb.publish import updater
    try:
        if a.attach:
            r = updater.attach()
            print(f"remote: {r['remote']}" + (" (connected this copy)" if r["attached"] else ""))
            return 0
        if a.finish:
            if updater.finish()["packages"]:
                print("packages updated")
            return 0
        if a.admin:
            p = updater.set_prefs(admin=a.admin == "on")
            print(f"admin mode {'on: About → Updates lists every branch as a channel' if p['admin'] else 'off'}"
                  f" (channel: {p['channel']})")
            return 0
        if a.branches:
            for b in updater.branches():
                print(f"{b['name']:<40} {b['date']}  {b['subject']}")
            return 0
        if a.check:
            r = updater.check()
            if r.get("error"):
                print(f"cannot check for updates: {r['error']}")
                return 1
            if r["off_channel"]:
                print(f"on branch {r['on_branch']}, not on the update channel {r['channel']}: updates are off")
                return 0
            if r["gone"]:
                print(f"branch {r['channel']} is gone (merged?): kb update returns to {r['default_channel']}")
                return 0
            print(f"channel {r['channel']}: " + (f"{r['behind']} new change(s) available" if r["available"] else "up to date"))
            for e in r["incoming"]:
                print(f"  {e['date']} {e['text']}")
            return 0
        r = updater.switch(a.channel) if a.channel else updater.rollback() if a.rollback else updater.apply()
        if a.rollback:
            print(f"rolled back to {r['to']} (version {r['version']})")
        elif not r["updated"]:
            print(r["message"])
            return 0
        else:
            print(f"updated {r['from']} → {r['to']} on {r['channel']} (version {r['version']})" + "".join(f"; {n}" for n in r["notes"]))
        updater.finish()
        return 0
    except updater.UpdateError as e:
        print(f"update failed: {e}")
        return 1


def cmd_tray(a) -> int:
    """The app without a console window: an icon in the notification area runs kb serve (Wiki.cmd starts this)."""
    from kb.publish import tray
    return tray.run()


def cmd_branding(a) -> int:
    """Project branding out of Git: pack branding.zip for a colleague, or import one (also refreshes the shortcut icon)."""
    from kb.publish import branding
    try:
        if a.action == "pack":
            print(f"created {branding.pack()}: send it; they drop it into Welcome or Settings → Project branding (or kb branding import)")
        elif a.action == "import":
            r = branding.import_zip(Path(a.zip).read_bytes())
            print(f"imported {', '.join(r['imported']) or 'no images'} into {r['folder']}; shortcut {r['shortcut']}"
                  + (f"; knowledge base title: {r['title']}" if r["title"] else ""))
        else:
            for k, v in branding.state()["files"].items():
                print(f"{k:<11} {v or '-'}")
        return 0
    except (OSError, ValueError) as e:
        print(f"branding: {e}")
        return 1


def cmd_pack(a) -> int:
    """Knowledge pack: export this knowledge base as one file for the team, or start from one (replaces wiki and sources)."""
    from kb.knowledge import pack
    try:
        if a.action == "export":
            r = pack.export(Path(a.file) if a.file else None)
            print(f"created {r['path']} ({r['bytes'] / 1e6:.0f} MB): {r['sources']} sources, {r['pages']} pages.\n"
                  "It holds company content: share it only through company channels (Teams, SharePoint), never GitHub.")
        else:
            if not a.file:
                print("kb pack import <file.kbpack.zip>")
                return 2
            r = pack.import_pack(Path(a.file))
            print(f"imported {r['title']!r}: {r['sources']} sources, {r['pages']} pages (made {r['created']}); "
                  "the previous wiki and sources are in the instance's Git history")
        return 0
    except (OSError, ValueError) as e:
        print(f"pack: {e}")
        return 1


def cmd_changelog(a) -> int:
    from kb.publish import changelog
    groups = changelog.groups()
    if a.md:
        print(changelog.markdown(groups, all_types=a.all))
        return 0
    for g in groups:
        entries = [e for e in g["entries"] if a.all or e["kind"] != "Other"]
        if entries:
            print(f"{g['version']}")
            for e in entries:
                print(f"  {e['date']} [{e['type']}] {e['text']}")
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
        print("no code repositories configured: kb serve → Settings → Code repositories (or code_repos in "
              "instance/config/profile.yaml: name, role, path, description)")
        return 1
    if chat.architecture():
        print("Architecture:\n" + "\n".join("  " + l for l in chat.architecture().splitlines()) + "\n")
    for r in rs:
        state = "MISSING" if not r["exists"] else f"{r.get('branch') or '?'}@{r['commit'] or '?'}" + (" (local changes)" if r["dirty"] else "")
        print(f"  {r['name']:<18} {r['role'] or '-':<14} {state:<24} {r['path']}\n  {'':<18} {r['description']}")
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


def cmd_assess(a) -> int:
    """Read-only: how the model judged each source after its ingest, next to what the ingest measurably produced."""
    import csv
    from kb.knowledge import assess
    if a.backfill or a.model:
        if a.model:
            print("The model reads each source again in its own read-only session: AI credits per source.")
        done = assess.backfill(with_model=a.model, ids=a.ids or None, force=a.force,
                               progress=lambda st, d: print(f"  {d}", flush=True))
        print(f"assessed {len(done)} source(s)" if done else "nothing to assess: every ingested source has an assessment"
              + ("" if a.model else " (--model adds the model's judgement, --force redoes them)"))
        return 0
    rows = [assess.row(x) for x in assess.load_all()]
    if a.verdict:
        rows = [r for r in rows if r["verdict"] == a.verdict]
    if a.csv:
        w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]) if rows else ["source_id"])
        w.writeheader(); w.writerows(rows)
        return 0
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print("no assessments yet: they are written by every ingest from version 0.14")
        return 0
    print(f"{'verdict':<9} " + " ".join(assess.ABBR[c] for c in assess.CRITERIA) + "  cit/10k pages  title")
    for r in rows:
        print(f"{r['verdict']:<9} " + " ".join(f"{str(r[k]):>3}" for k in assess.CRITERIA)
              + f"  {r['citations_per_10k_chars']:>7} {r['pages_citing']:>5}  {r['title'][:60]}")
    print("\nrel relevance · nov novelty · spe specificity · rlb reliability · txt text quality (1–5, the model's judgement);"
          "\ncit/10k citations of the source per 10,000 characters, pages citing it (measured). Reasons: --json")
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
    from kb.publish.settings import TOKEN_STEPS
    print("GitHub Copilot CLI not found. Install it (winget install GitHub.Copilot, or npm i -g @github/copilot),\n"
          "run `copilot login` once, then `kb llm-smoke`. Alternative: store a GitHub token in Settings → GitHub Copilot.\n"
          + TOKEN_STEPS)
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
    from kb.core.secrets import apply_env
    apply_env()  # a GitHub token stored in Settings / `kb secrets set copilot-github-token`
    ap = argparse.ArgumentParser(prog="kb", description="woynich-wiki knowledge base")
    ap.add_argument("--version", action="version", version=f"woynich-wiki {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the knowledge base instance (its own git repository)").set_defaults(fn=cmd_init)
    s = sub.add_parser("add", help="register files or folders as sources (one commit each)")
    s.add_argument("files", nargs="+"); s.add_argument("--title"); s.add_argument("--version"); s.set_defaults(fn=cmd_add)
    s = sub.add_parser("collect", help="collect sources: inbox folder, a git repository or Jira (JQL)")
    s.add_argument("what", choices=["inbox", "git", "jira"]); s.add_argument("--path"); s.add_argument("--ref", default="HEAD")
    s.add_argument("--glob", action="append"); s.add_argument("--jql"); s.add_argument("--limit", type=int); s.set_defaults(fn=cmd_collect)
    s = sub.add_parser("jira", help="Jira, read-only: get KEY… (print), search JQL (list), add KEY… (register as sources)")
    s.add_argument("action", choices=["get", "search", "add"]); s.add_argument("args", nargs="+")
    s.add_argument("--limit", type=int); s.add_argument("--links", action="store_true", help="add: also linked issues and sub-tasks")
    s.add_argument("--no-attachments", action="store_true")
    s.add_argument("--no-images", action="store_true", help="get: do not download the issue's pictures"); s.set_defaults(fn=cmd_jira)
    s = sub.add_parser("diagnostics", help="version and technical state for support, saved as instance/reports/diagnostics.json")
    s.add_argument("--adapter"); s.set_defaults(fn=cmd_diagnostics)
    s = sub.add_parser("check", help="test the GitHub Copilot sign-in and the Jira token (no AI credits used)")
    s.add_argument("--adapter"); s.set_defaults(fn=cmd_check)
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
    s = sub.add_parser("check-answer", help="check the citations of an answer (text, --file, or stdin with -) before showing it")
    s.add_argument("text", nargs="*"); s.add_argument("--file"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_check_answer)
    s = sub.add_parser("assess", help="quality of each ingested source: the model's scores and what the ingest produced (read-only)")
    s.add_argument("ids", nargs="*", help="only these source ids (with --backfill)")
    s.add_argument("--backfill", action="store_true", help="assess sources ingested earlier: measured signals, no AI credits")
    s.add_argument("--model", action="store_true", help="with the model's judgement too (one read-only session per source)")
    s.add_argument("--force", action="store_true", help="assess again even when an assessment exists")
    s.add_argument("--verdict", choices=["core", "useful", "marginal", "noise"]); s.add_argument("--json", action="store_true")
    s.add_argument("--csv", action="store_true"); s.set_defaults(fn=cmd_assess)
    s = sub.add_parser("verify", help="check links and citations on wiki pages (warnings only)"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("site", help="build the dashboard (instance/site/index.html)"); s.add_argument("--open", action="store_true"); s.set_defaults(fn=cmd_site)
    s = sub.add_parser("quota", help="AI credits used and left, when they reset (days, working days), what kb used this month")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_quota)
    s = sub.add_parser("serve", help="local web app: add files with visible steps, discussion sessions, dashboard")
    s.add_argument("--port", type=int, default=8765); s.add_argument("--no-browser", action="store_true"); s.add_argument("--adapter")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("update", help="update this copy of the app from its Git remote (as the Update button in kb serve)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="only say whether a newer version exists")
    g.add_argument("--rollback", action="store_true", help="back to the version before the last update")
    g.add_argument("--finish", action="store_true", help="install packages if the last update changed requirements.txt")
    g.add_argument("--attach", action="store_true", help="connect a ZIP copy to the official remote (setup does this)")
    g.add_argument("--channel", metavar="BRANCH", help="follow this branch from now on and move to it (admin mode; main always)")
    g.add_argument("--branches", action="store_true", help="admin mode: list the branches you can follow")
    g.add_argument("--admin", choices=["on", "off"], help="admin mode for this copy: every branch can be a channel")
    s.set_defaults(fn=cmd_update)
    s = sub.add_parser("tray", help="the app with a tray icon and no console window (Wiki.cmd starts it; --console there for the old way)")
    s.set_defaults(fn=cmd_tray)
    s = sub.add_parser("branding", help="project logo, background, icon and title (out of Git): show, pack branding.zip, import one")
    s.add_argument("action", nargs="?", choices=["show", "pack", "import"], default="show"); s.add_argument("zip", nargs="?", default="branding.zip")
    s.set_defaults(fn=cmd_branding)
    s = sub.add_parser("pack", help="knowledge pack: export this knowledge base for the team, or import one (replaces wiki and sources)")
    s.add_argument("action", choices=["export", "import"]); s.add_argument("file", nargs="?")
    s.set_defaults(fn=cmd_pack)
    s = sub.add_parser("changelog", help="what changed in each version, read from Git history")
    s.add_argument("--all", action="store_true", help="also docs, tests, refactoring"); s.add_argument("--md", action="store_true")
    s.set_defaults(fn=cmd_changelog)
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
