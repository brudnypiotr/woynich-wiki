"""Navigation in the configured code repositories: a file's outline (classes, methods, SQL objects, FitNesse headings,
named XML elements with their lines) and where a name is defined and used."""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from kb.knowledge.tools import repo


def available() -> bool:
    return bool(repo.repos())


def context() -> str:
    return "" if not available() else ("CODE (read-only): `find_symbol` (where a name is defined and used) and `code_outline` (a file's classes and "
            "methods with lines); view only the lines you need.")


class CodeOutline(BaseModel):
    repo: str = Field(description="Repository name")
    path: str = Field(description="File, relative to the repository root")


class FindSymbol(BaseModel):
    repo: str = Field(description="Repository name")
    name: str = Field(description="Exact name of a class, method, function, procedure, table or parameter")
    path: str = Field(default="", description="Only in this file or folder")


_MOD = r"(?:(?:public|private|protected|internal|static|abstract|final|sealed|partial|override|virtual|async|export|default|readonly|synchronized|extern|new)\s+)"
# (kind, pattern with one group for the name); checked in order, first match wins per line
OUTLINE = [
    ("class", re.compile(rf"^\s*{_MOD}*(?:class|interface|enum|record|struct|object|trait)\s+([A-Za-z_]\w*)")),
    ("def", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s+([A-Za-z_$][\w$]*)\s*\(")),
    ("sql", re.compile(r"^\s*(?:create|alter)\s+(?:or\s+replace\s+)?(?:procedure|function|table|view|trigger|package(?:\s+body)?|type)\s+([\w.\[\]\"]+)", re.I)),
    ("method", re.compile(rf"^\s*{_MOD}+[\w<>\[\],.?\s]*?\b([A-Za-z_]\w*)\s*\([^;{{]*\)?\s*(?:throws [\w., ]+)?\s*\{{?\s*$")),
    ("method", re.compile(r"^\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::\s*[\w<>\[\]|, ]+)?\s*\{\s*$")),  # TS/JS class methods
    ("section", re.compile(r"^!\d\s+(.+)")),  # FitNesse headings
    ("element", re.compile(r"^\s*<(\w[\w:.-]*)[^>]*\bname=\"([^\"]+)\"")),  # XML configuration: <rule name="…">
]
_NOT_METHODS = {"if", "for", "while", "switch", "catch", "return", "new", "else", "using", "lock", "foreach", "throw", "sizeof"}


def outline(text: str, limit: int = 400) -> list[tuple[int, str, str]]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for kind, rx in OUTLINE:
            m = rx.match(line)
            if not m:
                continue
            name = m.group(m.lastindex)
            if kind == "element":
                name = f"{m.group(1)} {m.group(2)}"
            if kind == "method" and name in _NOT_METHODS:
                break
            out.append((i, kind, name.strip()))
            break
        if len(out) >= limit:
            break
    return out


def _is_definition(line: str, name: str) -> bool:
    return any(kind in ("class", "def", "function", "sql", "method", "element") and m.group(m.lastindex).strip('"[]').split(".")[-1] == name
               for kind, rx in OUTLINE for m in [rx.match(line)] if m)


def tools() -> list:
    from copilot import define_tool
    from kb.knowledge.tools import off_loop

    @define_tool(description="Outline of a source file: classes, methods, functions, SQL objects, FitNesse headings or "
                             "named XML elements, each with its line number. Read it first, then view only the lines "
                             "you need instead of the whole file. Read-only.")
    @off_loop
    def code_outline(params: CodeOutline) -> str:
        r = next((x for x in repo.repos() if x["name"] == params.repo), None)
        if r is None:
            return f"unknown repository {params.repo!r}; use one of: " + ", ".join(x["name"] for x in repo.repos())
        try:
            f = (Path(r["path"]) / repo.relpath(params.path)).resolve()
        except ValueError as e:
            return str(e)
        if Path(r["path"]).resolve() not in f.parents or not f.is_file():
            return f"no such file in {params.repo}: {params.path}"
        text = f.read_text(encoding="utf-8", errors="replace")
        items = outline(text)
        head = f"{params.path}: {len(text.splitlines())} lines"
        return head + ("\n" + "\n".join(f"{n:>6}  {k:<8} {name}" for n, k, name in items) if items
                       else "\nno outline for this kind of file; view it with a line range")

    @define_tool(description="Where a name (class, method, function, procedure, table, parameter) is defined and "
                             "where it is used in a repository, with file and line: definitions first, then up to 60 "
                             "uses. Faster than searching file by file. Read-only.")
    @off_loop
    def find_symbol(params: FindSymbol) -> str:
        name = params.name.strip()
        if not re.fullmatch(r"[A-Za-z_$][\w$.]{0,120}", name):
            return "give one identifier, e.g. MaxFdpRule or calculate_rest"
        try:
            only = [repo.relpath(params.path)] if params.path.strip() else []
        except ValueError as e:
            return str(e)
        out = repo.git(params.repo, "grep", "-n", "-I", "-w", "-F", "-e", name.split(".")[-1], "--", *only)
        hits = [l for l in out.splitlines() if re.match(r"[^:]+:\d+:", l)]
        if not hits:
            return f"{name}: not found in {params.repo}" + ("" if out == "no output" or not out else f" ({out[:200]})")
        defs = [h for h in hits if _is_definition(h.split(":", 2)[2], name.split(".")[-1])]
        uses = [h for h in hits if h not in defs]
        commit = repo.short(params.repo, "HEAD")
        return (f"checked-out commit {commit}\nDEFINED ({len(defs)}):\n" + ("\n".join(defs[:20]) or "  none found (generated, "
                "external or defined in a way the outline does not recognise)") + f"\nUSED ({len(uses)}):\n" + "\n".join(uses[:60])
                + ("\n… more uses; narrow it down with path" if len(uses) > 60 else ""))

    return [code_outline, find_symbol]
