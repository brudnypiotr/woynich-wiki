from kb.extractors.base import paragraphs_to_md, segments
from kb.extractors.office import CodeExtractor, HtmlExtractor, TranscriptExtractor


def test_segments_roundtrip():
    segs = segments(paragraphs_to_md(["First para.", "", "Second para."]))
    assert segs == [("¶ 1", "First para."), ("¶ 2", "Second para.")]


def test_html_and_code(tmp_path):
    h = tmp_path / "a.html"
    h.write_text("<html><head><title>T</title></head><body><p>One &amp; two</p><script>x()</script><p>Three</p></body></html>")
    out = HtmlExtractor().extract(h)
    assert out["meta"]["title"] == "T" and "One & two" in out["text"] and "x()" not in out["text"]
    c = tmp_path / "x.py"
    c.write_text("\n".join(f"line{i}" for i in range(1, 25)))
    segs = dict(segments(CodeExtractor().extract(c)["text"]))
    assert segs["L11"].startswith("line11") and set(segs) == {"L1", "L11", "L21"}


def test_transcript_minutes(tmp_path):
    v = tmp_path / "m.vtt"
    v.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v A>Hello\n\n00:02:05.000 --> 00:02:06.000\n<v B>Later\n")
    segs = segments(TranscriptExtractor().extract(v)["text"])
    assert [l for l, _ in segs] == ["t. 00:00:01", "t. 00:02:05"] and "A: Hello" in segs[0][1]
