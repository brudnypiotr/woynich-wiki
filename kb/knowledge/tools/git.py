"""Git history and versions of the configured code repositories: who changed what, when and why (git_log,
git_show, git_blame), and other branches, tags and releases than the one checked out (git_refs, git_grep, git_diff)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from kb.knowledge.tools import repo


def available() -> bool:
    return bool(repo.repos())


def context() -> str:
    return "" if not available() else ("GIT (read-only): `git_log`, `git_show`, `git_blame` for who changed what, when and why (cite a commit as "
            "`name@hash`); `git_refs`, `git_grep`, `git_diff` for other branches, tags and releases than the one checked out.")


class GitLog(BaseModel):
    repo: str = Field(description="Repository name, as listed under CODE REPOSITORIES")
    path: str = Field(default="", description="Only commits touching this file or folder (relative to the repository root)")
    grep: str = Field(default="", description="Only commits whose message contains this text (e.g. a Jira key)")
    author: str = Field(default="", description="Only commits by this author (name or e-mail, part is enough)")
    since: str = Field(default="", description="Only commits since this date, YYYY-MM-DD")
    ref: str = Field(default="", description="Branch, tag or commit to start from (default: what is checked out)")
    limit: int = Field(default=20, description="Maximum number of commits (1-50)")


class GitShow(BaseModel):
    repo: str = Field(description="Repository name")
    commit: str = Field(description="Commit hash (at least 4 hex characters)")
    path: str = Field(default="", description="Show the change of this file only")


class GitBlame(BaseModel):
    repo: str = Field(description="Repository name")
    path: str = Field(description="File, relative to the repository root")
    start: int = Field(description="First line")
    end: int = Field(description="Last line (at most 200 lines after start)")


class GitRefs(BaseModel):
    repo: str = Field(description="Repository name")
    pattern: str = Field(default="", description="Only names containing this text (e.g. 2026.3, release, feature)")


class GitGrep(BaseModel):
    repo: str = Field(description="Repository name")
    text: str = Field(description="Text to find (exact, case-insensitive), e.g. a class, parameter or message")
    ref: str = Field(default="", description="Branch, tag or commit to search (default: what is checked out)")
    path: str = Field(default="", description="Only in this file or folder")


class GitDiff(BaseModel):
    repo: str = Field(description="Repository name")
    old: str = Field(description="Older branch, tag or commit, e.g. a release tag")
    new: str = Field(default="HEAD", description="Newer branch, tag or commit")
    path: str = Field(default="", description="Only this file or folder")
    stat_only: bool = Field(default=False, description="Only the list of changed files with counts (start with this)")


def tools() -> list:
    from copilot import define_tool

    @define_tool(description="Commit history of a code repository: hash, date, author and subject. Filter by file or "
                             "folder, message text (e.g. a Jira key), author, date, or start from a branch or tag. "
                             "Cite a commit as `repo@hash`. Read-only.")
    def git_log(params: GitLog) -> str:
        args = ["log", f"-n{max(1, min(50, params.limit))}", "--date=short", "--format=%h %ad %an <%ae> %s"]
        if params.grep.strip():
            args += ["-i", f"--grep={params.grep.strip()}"]
        if params.author.strip():
            args.append(f"--author={params.author.strip()}")
        if params.since.strip():
            if not repo.DATE.fullmatch(params.since.strip()):
                return "since must be a date YYYY-MM-DD"
            args.append(f"--since={params.since.strip()}")
        try:
            refs = [repo.ref(params.ref)] if params.ref.strip() else []
            return repo.git(params.repo, *args, *refs, "--", *([repo.relpath(params.path)] if params.path.strip() else []))
        except ValueError as e:
            return str(e)

    @define_tool(description="One commit of a code repository: author, date, full message, changed files and the diff "
                             "(optionally of one file only). Cite as `repo@hash`. Read-only.")
    def git_show(params: GitShow) -> str:
        if not repo.HASH.fullmatch(params.commit.strip()):
            return "commit must be a hash (4-40 hex characters)"
        try:
            only = [repo.relpath(params.path)] if params.path.strip() else []
        except ValueError as e:
            return str(e)
        return repo.git(params.repo, "show", "--no-ext-diff", "--no-textconv", "--stat", "--patch", "--date=iso",
                    "--format=commit %H%nAuthor: %an <%ae>%nDate: %ad%n%n%B", params.commit.strip(), "--", *only)

    @define_tool(description="Who last changed each line of a file (git blame): commit, author and date per line. "
                             "Use it to find the commit behind a rule or a value, then git_show it. Read-only.")
    def git_blame(params: GitBlame) -> str:
        start, end = max(1, params.start), max(1, params.end)
        if end < start or end - start > 200:
            return "give a range of at most 200 lines (start ≤ end)"
        try:
            return repo.git(params.repo, "blame", "--date=short", f"-L{start},{end}", "--", repo.relpath(params.path))
        except ValueError as e:
            return str(e)

    @define_tool(description="Branches and tags of a code repository (newest first) with their commit and date, and "
                             "what is checked out now. Use it before comparing versions or searching another branch. Read-only.")
    def git_refs(params: GitRefs) -> str:
        now = repo.git(params.repo, "rev-parse", "--abbrev-ref", "HEAD")
        out = repo.git(params.repo, "for-each-ref", "--sort=-committerdate", "--count=300",
                   "--format=%(refname:short) %(objectname:short) %(committerdate:short) %(subject)",
                   "refs/heads", "refs/remotes", "refs/tags")
        want = params.pattern.strip().lower()
        lines = [l for l in out.splitlines() if want in l.split(" ", 1)[0].lower()][:100]
        return f"checked out: {now}\n" + ("\n".join(lines) or "no branches or tags match")

    @define_tool(description="Search the code of a repository at a branch, tag or commit (default: what is checked "
                             "out): exact text, case-insensitive, with file and line. Use it to see what another version "
                             "contains. Cite as `repo/path:line@commit` with the commit given in the first line. Read-only.")
    def git_grep(params: GitGrep) -> str:
        text = params.text.strip()
        if not text:
            return "give a text to find"
        try:
            ref = repo.ref(params.ref)
            only = [repo.relpath(params.path)] if params.path.strip() else []
        except ValueError as e:
            return str(e)
        commit = repo.short(params.repo, ref)
        if not commit:
            return f"no branch, tag or commit {ref!r} in {params.repo}; see git_refs"
        out = repo.git(params.repo, "grep", "-n", "-I", "-i", "-F", "--max-count=50", "-e", text, commit, "--", *only)
        return f"{ref} = commit {commit}\n" + "\n".join(l.split(":", 1)[1] if l.startswith(commit + ":") else l for l in out.splitlines()[:300])

    @define_tool(description="What changed between two versions of a repository (branches, tags or commits): first "
                             "with stat_only to see the files, then for one file or folder. Read-only.")
    def git_diff(params: GitDiff) -> str:
        try:
            old, new = repo.ref(params.old), repo.ref(params.new)
            only = [repo.relpath(params.path)] if params.path.strip() else []
        except ValueError as e:
            return str(e)
        a, b = repo.short(params.repo, old), repo.short(params.repo, new)
        if not a or not b:
            return f"unknown branch, tag or commit ({old if not a else new}); see git_refs"
        mode = ["--stat"] if params.stat_only else ["--stat", "--patch"]
        return f"{old} = {a}, {new} = {b}\n" + repo.git(params.repo, "diff", "--no-ext-diff", "--no-textconv", *mode, a, b, "--", *only)

    return [git_log, git_show, git_blame, git_refs, git_grep, git_diff]
