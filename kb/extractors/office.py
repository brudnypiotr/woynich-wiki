"""Standard-library extractors (no extra dependencies): DOCX, HTML, email, transcripts, Jira JSON, code."""
from __future__ import annotations

import email
import html
import json
import re
import zipfile
from email import policy
from html.parser import HTMLParser
from pathlib import Path

from kb.core.ports import Extractor
from kb.extractors.base import marker, paragraphs_to_md

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxExtractor(Extractor):
    extensions = (".docx",)

    def extract(self, path: Path) -> dict:
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
        paras = []
        for p in root.iter(f"{W}p"):
            style = p.find(f"{W}pPr/{W}pStyle")
            txt = "".join(t.text or "" for t in p.iter(f"{W}t"))
            if style is not None and style.get(f"{W}val", "").lower().startswith("heading") and txt.strip():
                txt = "## " + txt
            paras.append(txt)
        return {"text": paragraphs_to_md(paras), "meta": {}}


class _Text(HTMLParser):
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "section", "article", "pre", "td"}
    SKIP = {"script", "style", "nav", "footer", "header", "noscript"}

    def __init__(self):
        super().__init__(); self.paras, self.buf, self.skip, self.title = [], [], 0, ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        if tag == "title": self._in_title = True
        if tag in self.BLOCK: self._flush()
        if tag in ("h1", "h2", "h3"): self.buf.append("## ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip: self.skip -= 1
        if tag == "title": self._in_title = False
        if tag in self.BLOCK: self._flush()

    def handle_data(self, data):
        if self._in_title: self.title += data
        elif not self.skip: self.buf.append(data)

    def _flush(self):
        t = "".join(self.buf).strip()
        if t and t != "##": self.paras.append(t)
        self.buf = []


class HtmlExtractor(Extractor):
    extensions = (".html", ".htm")

    def extract(self, path: Path) -> dict:
        raw = path.read_bytes()
        m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', raw[:4096])
        try:
            text = raw.decode(m.group(1).decode() if m else "utf-8", errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        p = _Text(); p.feed(text); p._flush()
        return {"text": paragraphs_to_md([html.unescape(x) for x in p.paras]), "meta": {"title": p.title.strip() or None}}


class EmailExtractor(Extractor):
    extensions = (".eml",)

    def extract(self, path: Path) -> dict:
        msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        body = msg.get_body(preferencelist=("plain", "html"))
        content = body.get_content() if body else ""
        if body and body.get_content_type() == "text/html":
            p = _Text(); p.feed(content); p._flush(); paras = p.paras
        else:
            paras = re.split(r"\n\s*\n", content)
        meta = {k: str(msg.get(k)) for k in ("From", "To", "Date", "Subject", "Message-ID") if msg.get(k)}
        if msg.get("Subject"): meta["title"] = str(msg.get("Subject"))
        meta["attachments"] = [a.get_filename() for a in msg.iter_attachments()]
        head = f"Subject: {meta.get('Subject', '')}\nFrom: {meta.get('From', '')}\nDate: {meta.get('Date', '')}"
        return {"text": paragraphs_to_md([head] + paras), "meta": meta}


class TranscriptExtractor(Extractor):
    """WebVTT / SRT (Teams, Zoom, Whisper output). One marker per minute; speaker tags kept."""
    extensions = (".vtt", ".srt")

    def extract(self, path: Path) -> dict:
        out, last_min, last_line, ts = [], None, None, None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^(\d{1,2}):(\d\d):(\d\d)[.,]\d+\s+-->", line) or re.match(r"^(\d\d):(\d\d)[.,]\d+\s+-->", line)
            if m:
                g = [int(x) for x in m.groups()]
                ts = g[0] * 3600 + g[1] * 60 + g[2] if len(g) == 3 else g[0] * 60 + g[1]
                continue
            line = re.sub(r"</?c[^>]*>|<\d\d:[^>]+>", "", line)
            line = re.sub(r"<v\s+([^>]+)>", r"\1: ", line).replace("</v>", "").strip()
            if not line or line.isdigit() or line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")) or line == last_line:
                continue
            if ts is not None and ts // 60 != last_min:
                last_min = ts // 60
                out.append(marker("t.", f"{ts // 3600:02d}:{(ts % 3600) // 60:02d}:{ts % 60:02d}"))
            out.append(line); last_line = line
        return {"text": "\n".join(out) + "\n", "meta": {}}


class JiraJsonExtractor(Extractor):
    """Issue JSON as returned by the Jira REST API (saved by the jira connector)."""
    extensions = (".jira.json",)

    def extract(self, path: Path) -> dict:
        issue = json.loads(path.read_text(encoding="utf-8"))
        f = issue.get("fields", {})
        out = [f"# {issue.get('key')}: {f.get('summary', '')}",
               f"Status: {(f.get('status') or {}).get('name')} · Resolution: {(f.get('resolution') or {}).get('name')} · Updated: {f.get('updated')}",
               "", marker("#description", ""), _adf_text(f.get("description")) or ""]
        for i, c in enumerate(((f.get("comment") or {}).get("comments") or []), 1):
            who = (c.get("author") or {}).get("displayName", "")
            out += ["", marker("#c", i), f"{who} ({c.get('created', '')}): {_adf_text(c.get('body'))}"]
        return {"text": "\n".join(out) + "\n", "meta": {"key": issue.get("key"), "title": f"{issue.get('key')}: {f.get('summary', '')}", "updated": f.get("updated"),
                                                        "status": (f.get("status") or {}).get("name")}}


class _Rich(HTMLParser):
    """Jira's rendered HTML (descriptions, comments) → plain text with lists, line breaks and simple tables."""
    BLOCK = {"p", "div", "ul", "ol", "table", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.pre, self.skip = [], 0, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "br":
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "tr":
            self.out.append("\n|")
        elif tag in ("td", "th"):
            self.out.append(" ")
        elif tag == "img":
            src = (a.get("src") or "").split("?")[0].rstrip("/").rsplit("/", 1)[-1]
            self.out.append(f" [image: {a.get('alt') or src}] ")
        elif tag in self.BLOCK:
            self.out.append("\n")
            self.pre += tag == "pre"

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        elif tag in ("td", "th"):
            self.out.append(" |")
        elif tag in self.BLOCK:
            self.out.append("\n")
            self.pre -= tag == "pre"

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data if self.pre else re.sub(r"\s+", " ", data))

    @classmethod
    def text(cls, src: str | None) -> str:
        p = cls(); p.feed(src or ""); p.close()
        lines = [l.rstrip() for l in "".join(p.out).splitlines()]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(l if l.strip() else "" for l in lines)).strip()


class JiraXmlExtractor(Extractor):
    """Jira XML issue view (saved by the jira connector): fields, links, custom fields, description, comments."""
    extensions = (".jira.xml",)
    SKIP_FIELDS = {"rank", "development", "team", "flagged", "[chart] date of first response", "last viewed"}

    def extract(self, path: Path) -> dict:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(path.read_bytes())
        item = root.find(".//item")
        item = root if item is None else item
        g = lambda tag: (item.findtext(tag) or "").strip()
        many = lambda tag: ", ".join(e.text.strip() for e in item.findall(tag) if e.text and e.text.strip())
        key = g("key")
        summary = g("summary") or re.sub(r"^\[[^\]]+\]\s*", "", g("title"))
        facts = [("Type", g("type")), ("Status", g("status")), ("Resolution", g("resolution")), ("Priority", g("priority")),
                 ("Assignee", g("assignee")), ("Reporter", g("reporter")), ("Created", g("created")), ("Updated", g("updated")),
                 ("Resolved", g("resolved")), ("Affects versions", many("version")), ("Fix versions", many("fixVersion")),
                 ("Components", many("component")), ("Labels", many("labels/label"))]
        out = [f"# {key}: {summary}", " · ".join(f"{k}: {v}" for k, v in facts if v)]
        links = []
        for t in item.findall("issuelinks/issuelinktype"):
            for side in ("outwardlinks", "inwardlinks"):
                for s in t.findall(side):
                    keys = [k.text.strip() for k in s.findall("issuelink/issuekey") if k.text]
                    if keys:
                        links.append(f"{s.get('description') or t.findtext('name') or 'linked'} {', '.join(keys)}")
        subs = [s.text.strip() for s in item.findall("subtasks/subtask") if s.text]
        if links or subs:
            out.append("Links: " + "; ".join(links + ([f"sub-tasks {', '.join(subs)}"] if subs else [])))
        custom = []
        for cf in item.findall("customfields/customfield"):
            name = (cf.findtext("customfieldname") or "").strip()
            vals = [_Rich.text(v.text) for v in cf.findall("customfieldvalues/customfieldvalue")]
            vals = [v for v in vals if v]
            if name and vals and name.lower() not in self.SKIP_FIELDS:
                custom.append(f"- {name}: {', '.join(vals)[:400]}")
        if custom:
            out += ["Custom fields:", *custom]
        atts = [f"{a.get('name')} ({max(1, int(a.get('size') or 0) // 1024)} KB)" for a in item.findall("attachments/attachment")]
        if atts:
            out.append("Attachments: " + ", ".join(atts))
        out += ["", marker("#description", ""), _Rich.text(g("description")) or "(no description)"]
        for i, c in enumerate(item.findall("comments/comment"), 1):
            out += ["", marker("#c", i), f"{c.get('author', '')} ({c.get('created', '')}): {_Rich.text(c.text)}"]
        return {"text": "\n".join(out) + "\n", "meta": {"key": key, "title": f"{key}: {summary}", "updated": g("updated"),
                                                        "status": g("status")}}


def _adf_text(node) -> str:
    """Atlassian Document Format (Jira Cloud) or plain string (Data Center) → text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        sep = "\n" if node.get("type") in ("paragraph", "heading", "listItem", "bulletList", "orderedList") else ""
        return sep.join(_adf_text(c) for c in node.get("content", [])).strip()
    if isinstance(node, list):
        return "\n".join(_adf_text(c) for c in node)
    return ""


class CodeExtractor(Extractor):
    extensions = (".py", ".cs", ".java", ".js", ".ts", ".sql", ".xml", ".json", ".yaml", ".yml", ".ps1", ".sh", ".config")

    def extract(self, path: Path) -> dict:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        out = []
        for i, line in enumerate(lines, 1):
            if i == 1 or i % 10 == 1:
                out.append(marker("L", i))
            out.append(line)
        return {"text": "\n".join(out) + "\n", "meta": {"lines": len(lines)}}
