"""XML and XSD: the file as it is, with line markers (cite `L 120`, as in code), decoded the way the file says (a BOM or
the `<?xml encoding=…?>` declaration: exports are often UTF-16 or windows-1250, not UTF-8).

Before the first marker (not citable, a map for the model): for an XSD the outline of the schema (elements, attributes,
types, allowed values, xs:documentation) with line numbers; for other XML the root element and the most common
elements, so a 20 000-line configuration file shows its shape at once.
"""
from __future__ import annotations

import codecs
import collections
import re
from pathlib import Path
from xml.parsers import expat

from kb.core.ports import Extractor
from kb.extractors.base import marker

MAX_OUTLINE = 300
XS = "http://www.w3.org/2001/XMLSchema"


def decode(raw: bytes) -> str:
    for bom, enc in ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16")):
        if raw.startswith(bom):
            return raw.decode(enc, errors="replace")
    if raw[:2] in (b"<\x00", b"\x00<"):  # UTF-16 without a BOM
        return raw.decode("utf-16-le" if raw[0] == 0x3C else "utf-16-be", errors="replace")
    m = re.match(rb'\s*<\?xml[^>]*encoding=["\']([A-Za-z0-9._-]+)["\']', raw[:300])
    try:
        return raw.decode(m[1].decode() if m else "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


class XmlExtractor(Extractor):
    extensions = (".xsd", ".xml")

    def extract(self, path: Path) -> dict:
        raw = path.read_bytes()
        text = decode(raw)
        schema = path.suffix.lower() == ".xsd"
        try:
            head, meta = (self._schema(text) if schema else self._shape(text)), {}
        except expat.ExpatError as e:
            head, meta = [f"(Not well-formed XML: {e}. The text below is the file as it is.)"], {"xml_error": str(e)}
        lines = text.splitlines()
        out = head + [""] if head else []
        for i, line in enumerate(lines, 1):
            if i == 1 or i % 10 == 1:
                out.append(marker("L", i))
            out.append(line)
        return {"text": "\n".join(out) + "\n", "meta": {"lines": len(lines), **meta}}

    @staticmethod
    def _parser(start, end=None, chars=None):
        p = expat.ParserCreate(namespace_separator=" ")
        p.StartElementHandler = lambda name, attrs: start(p, name, attrs)
        if end:
            p.EndElementHandler = lambda name: end(p, name)
        if chars:
            p.CharacterDataHandler = chars
        return p

    def _schema(self, text: str) -> list[str]:
        """Outline of an XSD: named elements, attributes and types with their line, allowed values, documentation."""
        items: list[list] = []   # [indent, text]
        stack: list[int | None] = []  # index in items of the named thing each open element belongs to
        doc = {"on": False, "buf": []}

        def start(p, name, attrs):
            ns, _, local = name.rpartition(" ")
            owner = next((s for s in reversed(stack) if s is not None), None)
            idx = None
            if ns == XS and len(items) < MAX_OUTLINE:
                depth = sum(1 for s in stack if s is not None)
                label = attrs.get("name") or (f"ref {attrs['ref']}" if attrs.get("ref") else None)
                if local in ("element", "attribute", "complexType", "simpleType", "group", "attributeGroup") and label:
                    typ = f": {attrs['type'].split(':')[-1]}" if attrs.get("type") else ""
                    occ = f" [{attrs.get('minOccurs', '1')}..{attrs.get('maxOccurs', '1')}]" if local == "element" and \
                        ("minOccurs" in attrs or "maxOccurs" in attrs) else ""
                    use = " (required)" if attrs.get("use") == "required" else ""
                    items.append([depth, f"{local} {label}{typ}{occ}{use} (L {p.CurrentLineNumber})"])
                    idx = len(items) - 1
                elif local == "enumeration" and owner is not None:
                    items[owner].append(attrs.get("value", ""))
                elif local == "documentation":
                    doc.update(on=True, buf=[])
            stack.append(idx)

        def end(p, name):
            if name.endswith(" documentation") and doc["on"]:
                owner = next((s for s in reversed(stack[:-1]) if s is not None), None)
                txt = " ".join("".join(doc["buf"]).split())
                if owner is not None and txt:
                    items[owner][1] += f': "{txt[:200]}"'
                doc["on"] = False
            stack.pop()

        def chars(data):
            if doc["on"]:
                doc["buf"].append(data)

        self._parser(start, end, chars).Parse(_without_declaration(text).encode("utf-8"), True)
        if not items:
            return []
        lines = ["Schema outline (a map; cite the numbered lines below):"]
        for it in items:
            values = it[2:]
            lines.append("  " * it[0] + "- " + it[1] + (f"; allowed values: {', '.join(values[:30])}" + (" …" if len(values) > 30 else "")
                                                       if values else ""))
        if len(items) >= MAX_OUTLINE:
            lines.append(f"(outline cut at {MAX_OUTLINE} items)")
        return lines

    def _shape(self, text: str) -> list[str]:
        """Root element and the most common elements of an XML file."""
        counts: collections.Counter = collections.Counter()
        root = {}

        def start(p, name, attrs):
            local = name.rpartition(" ")[2]
            if not root:
                root.update(name=local, line=p.CurrentLineNumber)
            counts[local] += 1

        self._parser(start).Parse(_without_declaration(text).encode("utf-8"), True)
        if not root or sum(counts.values()) < 20:  # small files speak for themselves
            return []
        common = ", ".join(f"<{n}> ×{c}" for n, c in counts.most_common(12))
        return [f"XML shape (a map; cite the numbered lines below): root <{root['name']}>, {sum(counts.values()):,} elements; "
                f"most common: {common}"]


def _without_declaration(text: str) -> str:
    """The text is already decoded: drop the declaration so expat does not decode it again as the declared encoding."""
    return re.sub(r"^﻿?\s*<\?xml[^>]*\?>", "", text, count=1)
