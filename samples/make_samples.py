"""Generate the fictional sample corpus (no real company or client data). Run: python samples/make_samples.py

Example Air is invented. The sources disagree on purpose: the operations manual says 12 hours minimum rest at
home base, a later meeting and a Jira ticket say the rule engine uses 10 hours. The ingest should flag it ⚖️.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent / "sources"

OM_PAGES = [
    ["Example Air", "Operations Manual Part A", "Chapter 7: Flight and Duty Time Limitations", "",
     "Revision 4, effective 1 January 2026", "Fictional document for testing the knowledge base."],
    ["7.1 Definitions", "",
     "Flight Duty Period (FDP) means a period that starts when a crew member reports for duty",
     "and finishes when the aircraft finally comes to rest after the last sector.",
     "Window of Circadian Low (WOCL) means the period between 02:00 and 05:59 in the time zone",
     "to which the crew member is acclimatised.",
     "Home base is the location assigned by the operator where the crew member normally starts duty."],
    ["7.4 Minimum rest", "",
     "The minimum rest period before a flight duty period starting at home base is 12 hours",
     "or the length of the preceding duty period, whichever is greater.",
     "The minimum rest period away from home base is 10 hours, including 8 hours of sleep opportunity.",
     "Rest periods must be planned in the roster and published at least 14 days in advance."],
    ["7.5 Extended rest", "",
     "Each crew member must receive a recurrent extended rest period of 36 hours including two local nights",
     "so that there are never more than 168 hours between the end of one extended rest and the start of the next.",
     "Table 7.5: Extended rest", "Period | Minimum | Nights", "Recurrent | 36 hours | 2 local nights",
     "After 4 time zones | 48 hours | 2 local nights"],
]


def pdf(pages: list[list[str]]) -> bytes:
    """Minimal PDF writer: one Helvetica text page per list of lines (enough for text extraction tests)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for lines in pages:
        esc = [l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for l in lines]
        stream = "BT /F1 11 Tf 14 TL 60 780 Td " + " ".join(f"({l}) Tj T*" for l in esc) + " ET"
        objs.append(f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream")
        content = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info << /Title (Example Air OM-A Chapter 7) >> >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


VTT = """WEBVTT

00:00:05.000 --> 00:00:12.000
<v Anna (Rules team)>Let's go through the Example Air rest rules before the release.

00:01:10.000 --> 00:01:20.000
<v Marek (Delivery)>Since the March change the rule engine uses 10 hours minimum rest at home base for Example Air.

00:01:21.000 --> 00:01:30.000
<v Anna (Rules team)>That does not match the operations manual, which still says 12 hours. We need a decision from the client.

00:02:40.000 --> 00:02:52.000
<v Marek (Delivery)>Extended rest stays at 36 hours with two local nights, no change there.
"""

JIRA = {"key": "EXA-142", "fields": {
    "summary": "Minimum rest at home base: rule engine uses 10 h",
    "status": {"name": "In Review"}, "resolution": None, "updated": "2026-03-18T10:12:00.000+0100",
    "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text",
        "text": "Client request: reduce the minimum rest period before a duty starting at home base from 12 hours to 10 hours. "
                "The rule MinRestHomeBase reads the value from the parameter MIN_REST_HOME_BASE_HOURS."}]}]},
    "comment": {"comments": [
        {"author": {"displayName": "Marek"}, "created": "2026-03-12T09:00:00.000+0100",
         "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text",
             "text": "Parameter MIN_REST_HOME_BASE_HOURS changed to 10 in the Example Air configuration."}]}]}},
        {"author": {"displayName": "Anna"}, "created": "2026-03-18T10:12:00.000+0100",
         "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text",
             "text": "The operations manual revision 4 still says 12 hours. Waiting for the client to publish an OM revision."}]}]}}]}}}

EML = """From: ops.standards@example-air.example
To: rules-team@example.com
Subject: Example Air: rest rules for summer roster
Date: Mon, 6 Apr 2026 09:30:00 +0200
Content-Type: text/plain; charset=utf-8

Hello,

For the summer roster please keep the standby rule unchanged: airport standby counts fully as duty.

The revision of the operations manual with the new minimum rest is planned for June 2026. Until then the published OM applies.

Best regards,
Operations Standards, Example Air
"""

CODE = '''"""Example rule (fictional): minimum rest before a duty that starts at home base."""

from rules.params import get_param


class MinRestHomeBase:
    """Checks that the rest before a home-base duty is long enough."""

    name = "MIN_REST_HOME_BASE"

    def required_hours(self, airline: str, previous_duty_hours: float) -> float:
        base = get_param(airline, "MIN_REST_HOME_BASE_HOURS")  # 10 for EXA since EXA-142
        return max(base, previous_duty_hours)

    def check(self, airline: str, previous_duty_hours: float, rest_hours: float) -> bool:
        return rest_hours >= self.required_hours(airline, previous_duty_hours)
'''

PARAMS = '''"""Rule parameters per airline (fictional)."""

PARAMS = {
    "EXA": {"MIN_REST_HOME_BASE_HOURS": 10, "MIN_REST_AWAY_HOURS": 10, "EXTENDED_REST_HOURS": 36},
    "DEFAULT": {"MIN_REST_HOME_BASE_HOURS": 12, "MIN_REST_AWAY_HOURS": 10, "EXTENDED_REST_HOURS": 36},
}


def get_param(airline: str, name: str):
    return PARAMS.get(airline, PARAMS["DEFAULT"]).get(name, PARAMS["DEFAULT"][name])
'''


def main():
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / "example-air-om-a-ch7.pdf").write_bytes(pdf(OM_PAGES))
    (HERE / "rules-review-meeting.vtt").write_text(VTT, encoding="utf-8")
    (HERE / "EXA-142.jira.json").write_text(json.dumps(JIRA, indent=1), encoding="utf-8")
    (HERE / "summer-roster-rules.eml").write_text(EML, encoding="utf-8")
    repo = Path(__file__).parent / "code-repo" / "rules"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "min_rest.py").write_text(CODE, encoding="utf-8")
    (repo / "params.py").write_text(PARAMS, encoding="utf-8")
    (repo / "__init__.py").write_text("", encoding="utf-8")
    print(f"samples written to {HERE.parent}")


if __name__ == "__main__":
    main()
