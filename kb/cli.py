"""Command line: `python -m kb <command>` (setup also creates a `kb.cmd` shim)."""
from __future__ import annotations

import argparse
import sys

from kb import __version__
from kb.core import config, registry

INSTANCE_DIRS = ["inbox", "raw", "catalog", "queue", "wiki", "reports", "config"]


def cmd_init(a) -> int:
    p = config.paths()
    for d in INSTANCE_DIRS:
        (p.instance / d).mkdir(parents=True, exist_ok=True)
    print(f"instance ready: {p.instance}")
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
    """Sign in to GitHub Copilot with the runtime downloaded by the Copilot SDK (device / browser flow)."""
    import subprocess
    try:
        from copilot import _cli_download as dl
    except ImportError:
        print("Copilot SDK not installed. Run setup.cmd first."); return 2
    cli = dl.get_cached_cli_path() or dl.download_cli()
    return subprocess.call([cli, "login"])


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
    ap = argparse.ArgumentParser(prog="kb", description="woynich-wiki knowledge base")
    ap.add_argument("--version", action="version", version=f"woynich-wiki {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the instance folders").set_defaults(fn=cmd_init)
    sub.add_parser("plugins", help="list registered plugins").set_defaults(fn=cmd_plugins)
    sub.add_parser("login", help="sign in to GitHub Copilot (once)").set_defaults(fn=cmd_login)
    sub.add_parser("llm-smoke", help="spike S1: test model access from scripts").set_defaults(fn=cmd_llm_smoke)
    s = sub.add_parser("secrets", help="store or check a secret (Jira token, ...)")
    s.add_argument("action", choices=["set", "check"]); s.add_argument("name")
    s.add_argument("--store", default="keyring"); s.set_defaults(fn=cmd_secrets)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
